"""探测 Ozon/WB 是否有支持小时级数据的"隐藏"端点 v2

关键新发现要验证：
- Ozon Seller /v1/analytics/data 接受 dimension=["hour"] 但响应可能静默忽略 hour
  → 单独只传 ["hour"] 看看结果

WB 广告端点补测（第一版用了错误的方法名）：
- /adv/v3/fullstats GET 带 T23:59:59 的时间戳
- /adv/v2/fullstats POST
- /adv/v1/fullstats POST
- /adv/v2/auto/stat
- /adv/v1/stat/words
- /adv/v1/promotion/count
- /adv/v1/seacat/stat  搜索目录
- /adv/v2/auto/daily/stat
"""
import asyncio
import json
import sys
from datetime import date

sys.path.insert(0, "/data/ecommerce-ai")

from app.database import SessionLocal
from app.models.shop import Shop
from app.services.platform.ozon import OzonClient, OZON_PERFORMANCE_API, OZON_SELLER_API
from app.services.platform.wb import WBClient, WB_ADVERT_API, WB_STATISTICS_API

TARGET_DATE = "2026-04-14"
WB_TEST_ADVERT_IDS = ["32319603", "33121342", "35104408"]


async def try_req(client, label: str, method: str, url: str, use_perf=False, **kwargs):
    print(f"\n--- {label} ---")
    print(f"  {method} {url}")
    body_preview = ""
    if "json" in kwargs:
        body_preview = f"body: {json.dumps(kwargs['json'], ensure_ascii=False)[:250]}"
        print(f"  {body_preview}")
    if "params" in kwargs:
        print(f"  params: {kwargs['params']}")
    try:
        if use_perf:
            resp = await client._request(method, url, use_perf=True, **kwargs)
        else:
            resp = await client._request(method, url, **kwargs)
        body_str = json.dumps(resp, ensure_ascii=False, default=str)[:1500]
        print(f"  OK body={body_str}")
        return {"label": label, "ok": True, "body": body_str}
    except Exception as e:
        msg = str(e)[:400]
        resp_body = ""
        if hasattr(e, "response"):
            try:
                resp_body = e.response.text[:500]
            except Exception:
                pass
        print(f"  ERR {msg}")
        if resp_body:
            print(f"  response body: {resp_body}")
        return {"label": label, "ok": False, "err": msg, "resp_body": resp_body}


async def probe_ozon():
    db = SessionLocal()
    shop = db.query(Shop).filter(Shop.platform == "ozon", Shop.status == "active").first()
    ozon = OzonClient(
        shop_id=shop.id, api_key=shop.api_key, client_id=shop.client_id,
        perf_client_id=shop.perf_client_id, perf_client_secret=shop.perf_client_secret,
    )
    db.close()

    results = []

    # 1. analytics/data 单独 hour 维度（不带 sku 混淆）
    results.append(await try_req(ozon, "seller analytics dim=[hour] only",
        "POST", f"{OZON_SELLER_API}/v1/analytics/data",
        json={
            "date_from": TARGET_DATE, "date_to": TARGET_DATE,
            "dimension": ["hour"],
            "metrics": ["hits_view", "hits_tocart", "ordered_units", "revenue"],
            "limit": 100, "offset": 0,
        }))

    # 2. analytics/data dim=[day,hour] 两个维度
    results.append(await try_req(ozon, "seller analytics dim=[day,hour]",
        "POST", f"{OZON_SELLER_API}/v1/analytics/data",
        json={
            "date_from": TARGET_DATE, "date_to": TARGET_DATE,
            "dimension": ["day", "hour"],
            "metrics": ["hits_view", "ordered_units", "revenue"],
            "limit": 100, "offset": 0,
        }))

    # 3. analytics/data dim=["hour","day","sku"]
    results.append(await try_req(ozon, "seller analytics dim=[hour,day,sku]",
        "POST", f"{OZON_SELLER_API}/v1/analytics/data",
        json={
            "date_from": TARGET_DATE, "date_to": TARGET_DATE,
            "dimension": ["hour", "day", "sku"],
            "metrics": ["hits_view"],
            "limit": 100, "offset": 0,
        }))

    # 4. Ozon Seller finance transaction list — 广告扣费交易可能带时间戳
    results.append(await try_req(ozon, "seller finance/transaction/list v3",
        "POST", f"{OZON_SELLER_API}/v3/finance/transaction/list",
        json={
            "filter": {
                "date": {"from": f"{TARGET_DATE}T00:00:00.000Z", "to": f"{TARGET_DATE}T23:59:59.999Z"},
                "operation_type": ["ClientReturnAgentOperation", "MarketplaceMarketingActionCostOperation"],
                "transaction_type": "all",
            },
            "page": 1, "page_size": 10,
        }))

    return results


async def probe_wb():
    db = SessionLocal()
    shop = db.query(Shop).filter(Shop.platform == "wb", Shop.status == "active").first()
    wb = WBClient(shop_id=shop.id, api_key=shop.api_key)
    db.close()

    advert_id = WB_TEST_ADVERT_IDS[0]
    results = []

    # v3/fullstats GET 用 interval 格式（T00:00:00 到 T23:59:59）
    results.append(await try_req(wb, "v3/fullstats GET interval timestamps",
        "GET", f"{WB_ADVERT_API}/adv/v3/fullstats",
        params={
            "ids": advert_id,
            "beginDate": f"{TARGET_DATE}T00:00:00",
            "endDate": f"{TARGET_DATE}T23:59:59",
        }))

    # v3/fullstats POST（官方有的版本是 POST）
    results.append(await try_req(wb, "v3/fullstats POST body",
        "POST", f"{WB_ADVERT_API}/adv/v3/fullstats",
        json=[{"id": int(advert_id), "dates": [TARGET_DATE]}]))

    # v2/fullstats
    results.append(await try_req(wb, "v2/fullstats POST",
        "POST", f"{WB_ADVERT_API}/adv/v2/fullstats",
        json=[{"id": int(advert_id), "dates": [TARGET_DATE]}]))

    # v1/fullstats
    results.append(await try_req(wb, "v1/fullstats POST",
        "POST", f"{WB_ADVERT_API}/adv/v1/fullstats",
        json={"id": int(advert_id), "begin": TARGET_DATE, "end": TARGET_DATE}))

    # 自动广告日级
    results.append(await try_req(wb, "v2/auto/daily/stat",
        "GET", f"{WB_ADVERT_API}/adv/v2/auto/daily/stat",
        params={"id": advert_id}))

    # 关键词统计
    results.append(await try_req(wb, "v1/stat/words",
        "GET", f"{WB_ADVERT_API}/adv/v1/stat/words",
        params={"id": advert_id}))

    # 搜索目录活动统计
    results.append(await try_req(wb, "v1/seacat/stat",
        "GET", f"{WB_ADVERT_API}/adv/v1/seacat/stat",
        params={"id": advert_id}))

    # WB 内容统计 — 按日期详细报表
    results.append(await try_req(wb, "statistics-api reportDetailByPeriod v5",
        "GET", f"{WB_STATISTICS_API}/api/v5/supplier/reportDetailByPeriod",
        params={"dateFrom": TARGET_DATE, "dateTo": TARGET_DATE}))

    # WB 销售（不是广告但看时间粒度）
    results.append(await try_req(wb, "statistics-api supplier/sales",
        "GET", f"{WB_STATISTICS_API}/api/v1/supplier/sales",
        params={"dateFrom": f"{TARGET_DATE}T00:00:00", "flag": 1}))

    return results


async def main():
    print("=" * 60)
    print("OZON 端点探测 v2")
    print("=" * 60)
    ozon_results = await probe_ozon()

    print("\n" + "=" * 60)
    print("WB 端点探测 v2")
    print("=" * 60)
    wb_results = await probe_wb()

    print("\n\n" + "=" * 60)
    print("汇总")
    print("=" * 60)
    print("\n-- Ozon --")
    for r in ozon_results:
        status = "OK" if r["ok"] else "ERR"
        hint = r.get("body", "") if r["ok"] else (r.get("resp_body") or r.get("err", ""))[:200]
        print(f"  [{status}] {r['label']:45s} {hint[:200]}")
    print("\n-- WB --")
    for r in wb_results:
        status = "OK" if r["ok"] else "ERR"
        hint = r.get("body", "") if r["ok"] else (r.get("resp_body") or r.get("err", ""))[:200]
        print(f"  [{status}] {r['label']:45s} {hint[:200]}")


if __name__ == "__main__":
    asyncio.run(main())
