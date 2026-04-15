"""探测 Ozon Performance API 是否支持小时级数据

策略：对某个已知有数据的 Ozon 店铺，用 04-14 一天数据试 groupBy 的各种取值，
看哪些不被 400 拒绝、哪些真的返回了小时维度。

用法：
    python3 scripts/probe_ozon_hourly.py
"""
import asyncio
import json
import sys
from datetime import date

sys.path.insert(0, "/data/ecommerce-ai")

from app.database import SessionLocal
from app.models.shop import Shop
from app.models.ad import AdCampaign
from app.services.platform.ozon import OzonClient

TARGET_DATE = "2026-04-14"
CANDIDATES = ["DATE", "HOUR", "DATE_HOUR", "DATE,HOUR", "DAY_HOUR", "day_hour", "hour", "DAY", "DATE_AND_HOUR"]


async def probe(ozon: OzonClient, campaign_ids: list, group_by: str) -> dict:
    """提交一次请求，返回 {status, state, sample_row, error, row_count}"""
    from app.services.platform.ozon import OZON_PERFORMANCE_API

    try:
        submit = await ozon._request(
            "POST",
            f"{OZON_PERFORMANCE_API}/api/client/statistics/json",
            use_perf=True,
            json={
                "campaigns": campaign_ids,
                "dateFrom": TARGET_DATE,
                "dateTo": TARGET_DATE,
                "groupBy": group_by,
            },
        )
    except Exception as e:
        return {"groupBy": group_by, "submit_error": str(e)[:500]}

    uuid = submit.get("UUID")
    if not uuid:
        return {"groupBy": group_by, "submit_response": submit}

    for _ in range(24):
        await asyncio.sleep(5)
        try:
            data = await ozon._request(
                "GET",
                f"{OZON_PERFORMANCE_API}/api/client/statistics/{uuid}",
                use_perf=True,
            )
        except Exception as e:
            return {"groupBy": group_by, "poll_error": str(e)[:500]}

        state = data.get("state")
        if state == "OK":
            link = data.get("link", "")
            if not link:
                return {"groupBy": group_by, "state": "OK_NO_LINK", "data": data}
            try:
                report = await ozon._request("GET", f"{OZON_PERFORMANCE_API}{link}", use_perf=True)
            except Exception as e:
                return {"groupBy": group_by, "download_error": str(e)[:500]}

            sample_rows = []
            total_rows = 0
            for cid, cdata in report.items():
                if not isinstance(cdata, dict):
                    continue
                rows = cdata.get("report", {}).get("rows", [])
                total_rows += len(rows)
                if len(sample_rows) < 3 and rows:
                    sample_rows.extend(rows[:3])

            return {
                "groupBy": group_by,
                "state": "OK",
                "row_count": total_rows,
                "sample_rows": sample_rows[:3],
                "top_level_keys": list(report.keys())[:5],
            }
        if state in ("ERROR", "CANCELLED"):
            return {"groupBy": group_by, "state": state, "data": data}

    return {"groupBy": group_by, "state": "TIMEOUT"}


async def main():
    db = SessionLocal()
    shop = db.query(Shop).filter(Shop.platform == "ozon", Shop.status == "active").first()
    if not shop:
        print("找不到 active 的 Ozon 店铺")
        return
    print(f"店铺: id={shop.id} name={shop.name}")

    # 04-14 真有数据的 Ozon 活动（imp/clk 大于 0）
    platform_cids = ["24664750", "16319347", "24463141", "16756542", "24463338", "24459320"]
    print(f"活动: {platform_cids}")

    ozon = OzonClient(
        shop_id=shop.id,
        api_key=shop.api_key,
        client_id=shop.client_id,
        perf_client_id=shop.perf_client_id,
        perf_client_secret=shop.perf_client_secret,
    )
    await ozon._ensure_perf_token()
    db.close()

    results = []
    for gb in CANDIDATES:
        print(f"\n=== 探测 groupBy={gb} ===")
        r = await probe(ozon, platform_cids, gb)
        results.append(r)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str)[:2000])
        await asyncio.sleep(3)

    print("\n\n==== 汇总 ====")
    for r in results:
        gb = r.get("groupBy")
        state = r.get("state") or r.get("submit_error", "")[:80] or "?"
        rc = r.get("row_count", "-")
        sample_keys = list(r.get("sample_rows", [{}])[0].keys()) if r.get("sample_rows") else []
        print(f"  {gb:20s}  state={state:20s}  rows={rc}  sample_keys={sample_keys}")


if __name__ == "__main__":
    asyncio.run(main())
