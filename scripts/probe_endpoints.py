"""探测 Ozon/WB 是否有支持小时级数据的"隐藏"端点

Ozon 方向（A）：
  - Performance API: statistics/daily/json, statistics/video/json, statistics/phrases/json,
    statistics/attribution, statistics/orders, statistics/expense
  - Seller API: /v1/analytics/data（可以传 dimension=hour/day/week/month）
  - Seller API: /v1/analytics/stocks_on_warehouses, /v1/finance/realization

WB 方向（C）：
  - /adv/v2/auto/stat（自动广告）
  - /adv/v1/stat/words（关键词统计）
  - /adv/v1/fullstats（v1 旧版）
  - /adv/v2/fullstats（v2 旧版）
  - statistics-api /api/v1/supplier/reportDetailByPeriod
  - statistics-api /api/v5/supplier/reportDetailByPeriod
"""
import asyncio
import json
import sys
import traceback
from datetime import date

sys.path.insert(0, "/data/ecommerce-ai")

from app.database import SessionLocal
from app.models.shop import Shop
from app.services.platform.ozon import OzonClient, OZON_PERFORMANCE_API, OZON_SELLER_API
from app.services.platform.wb import WBClient, WB_ADVERT_API, WB_STATISTICS_API

TARGET_DATE = "2026-04-14"


async def try_ozon(ozon: OzonClient, label: str, method: str, url: str, **kwargs):
    """试一个端点，捕获所有错误，返回 {label, status, body_summary}"""
    print(f"\n--- Ozon: {label} ---")
    print(f"  {method} {url}")
    if "json" in kwargs:
        print(f"  body: {json.dumps(kwargs['json'], ensure_ascii=False)[:200]}")
    try:
        resp = await ozon._request(method, url, **kwargs)
        body_str = json.dumps(resp, ensure_ascii=False, default=str)[:800]
        print(f"  OK body={body_str}")
        return {"label": label, "ok": True, "body": body_str}
    except Exception as e:
        msg = str(e)[:500]
        # 尝试取 response body
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


async def try_wb(wb: WBClient, label: str, method: str, url: str, **kwargs):
    print(f"\n--- WB: {label} ---")
    print(f"  {method} {url}")
    if "json" in kwargs:
        print(f"  body: {json.dumps(kwargs['json'], ensure_ascii=False)[:200]}")
    if "params" in kwargs:
        print(f"  params: {kwargs['params']}")
    try:
        resp = await wb._request(method, url, **kwargs)
        body_str = json.dumps(resp, ensure_ascii=False, default=str)[:800]
        print(f"  OK body={body_str}")
        return {"label": label, "ok": True, "body": body_str}
    except Exception as e:
        msg = str(e)[:500]
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
    if not shop:
        print("无 Ozon 店铺")
        return []
    ozon = OzonClient(
        shop_id=shop.id, api_key=shop.api_key, client_id=shop.client_id,
        perf_client_id=shop.perf_client_id, perf_client_secret=shop.perf_client_secret,
    )
    await ozon._ensure_perf_token()
    db.close()

    results = []
    # Performance API 其他子路径
    results.append(await try_ozon(ozon, "perf statistics/daily/json",
        "POST", f"{OZON_PERFORMANCE_API}/api/client/statistics/daily/json",
        use_perf=True, json={"campaigns": ["24664750"], "dateFrom": TARGET_DATE, "dateTo": TARGET_DATE}))

    results.append(await try_ozon(ozon, "perf statistics/video/json",
        "POST", f"{OZON_PERFORMANCE_API}/api/client/statistics/video/json",
        use_perf=True, json={"campaigns": ["24664750"], "dateFrom": TARGET_DATE, "dateTo": TARGET_DATE}))

    results.append(await try_ozon(ozon, "perf statistics/phrases/json",
        "POST", f"{OZON_PERFORMANCE_API}/api/client/statistics/phrases/json",
        use_perf=True, json={"campaigns": ["24664750"], "dateFrom": TARGET_DATE, "dateTo": TARGET_DATE}))

    results.append(await try_ozon(ozon, "perf statistics/attribution",
        "POST", f"{OZON_PERFORMANCE_API}/api/client/statistics/attribution",
        use_perf=True, json={"campaigns": ["24664750"], "dateFrom": TARGET_DATE, "dateTo": TARGET_DATE}))

    results.append(await try_ozon(ozon, "perf statistics/orders",
        "POST", f"{OZON_PERFORMANCE_API}/api/client/statistics/orders",
        use_perf=True, json={"campaigns": ["24664750"], "dateFrom": TARGET_DATE, "dateTo": TARGET_DATE}))

    results.append(await try_ozon(ozon, "perf statistics/expense",
        "POST", f"{OZON_PERFORMANCE_API}/api/client/statistics/expense",
        use_perf=True, json={"campaigns": ["24664750"], "dateFrom": TARGET_DATE, "dateTo": TARGET_DATE}))

    # Performance API 的 statistics list（列出可用报表）
    results.append(await try_ozon(ozon, "perf statistics/list",
        "POST", f"{OZON_PERFORMANCE_API}/api/client/statistics/list",
        use_perf=True, json={}))

    # Seller API Analytics（支持 dimension=day/week/month，看是否有 hour）
    results.append(await try_ozon(ozon, "seller v1/analytics/data dim=hour",
        "POST", f"{OZON_SELLER_API}/v1/analytics/data",
        json={
            "date_from": TARGET_DATE, "date_to": TARGET_DATE,
            "dimension": ["hour", "sku"],
            "metrics": ["hits_view", "hits_tocart", "ordered_units", "revenue"],
            "limit": 10, "offset": 0,
        }))

    results.append(await try_ozon(ozon, "seller v1/analytics/data dim=day",
        "POST", f"{OZON_SELLER_API}/v1/analytics/data",
        json={
            "date_from": TARGET_DATE, "date_to": TARGET_DATE,
            "dimension": ["day", "sku"],
            "metrics": ["hits_view", "ordered_units", "revenue"],
            "limit": 10, "offset": 0,
        }))

    return results


async def probe_wb():
    db = SessionLocal()
    shop = db.query(Shop).filter(Shop.platform == "wb", Shop.status == "active").first()
    if not shop:
        print("无 WB 店铺")
        return []
    wb = WBClient(shop_id=shop.id, api_key=shop.api_key)
    db.close()

    # 先拿个活动 id
    try:
        camps = await wb.fetch_campaigns()
        advert_id = None
        for c in camps[:30]:
            advert_id = c.get("platform_campaign_id") or c.get("advertId") or c.get("id")
            if advert_id:
                break
        print(f"WB 测试活动 ID: {advert_id}")
    except Exception as e:
        print(f"WB fetch_campaigns 失败: {e}")
        advert_id = None

    results = []
    # v3/fullstats 带时间戳参数（试着塞 from=datetime）
    if advert_id:
        results.append(await try_wb(wb, "v3/fullstats params with dates+hour",
            "GET", f"{WB_ADVERT_API}/adv/v3/fullstats",
            params={"ids": str(advert_id), "beginDate": f"{TARGET_DATE}T00:00:00", "endDate": f"{TARGET_DATE}T23:59:59"}))

        # v2/fullstats
        results.append(await try_wb(wb, "v2/fullstats",
            "POST", f"{WB_ADVERT_API}/adv/v2/fullstats",
            json=[{"id": int(advert_id), "dates": [TARGET_DATE]}]))

        # v1/fullstats
        results.append(await try_wb(wb, "v1/fullstats",
            "POST", f"{WB_ADVERT_API}/adv/v1/fullstats",
            json={"id": int(advert_id), "begin": TARGET_DATE, "end": TARGET_DATE}))

        # 自动广告小时级? /adv/v2/auto/stat
        results.append(await try_wb(wb, "v2/auto/stat",
            "GET", f"{WB_ADVERT_API}/adv/v2/auto/stat",
            params={"id": int(advert_id)}))

        # 关键词统计
        results.append(await try_wb(wb, "v1/stat/words",
            "GET", f"{WB_ADVERT_API}/adv/v1/stat/words",
            params={"id": int(advert_id)}))

    # statistics-api — 供应商报表
    results.append(await try_wb(wb, "statistics-api supplier/orders",
        "GET", f"{WB_STATISTICS_API}/api/v1/supplier/orders",
        params={"dateFrom": f"{TARGET_DATE}T00:00:00", "flag": 1}))

    return results


async def main():
    print("=" * 60)
    print("OZON 端点探测")
    print("=" * 60)
    ozon_results = await probe_ozon()

    print("\n" + "=" * 60)
    print("WB 端点探测")
    print("=" * 60)
    wb_results = await probe_wb()

    print("\n\n" + "=" * 60)
    print("汇总")
    print("=" * 60)
    print("\n-- Ozon --")
    for r in ozon_results:
        status = "OK" if r["ok"] else "ERR"
        hint = r.get("body", "") if r["ok"] else (r.get("resp_body") or r.get("err", ""))[:150]
        print(f"  [{status}] {r['label']:40s} {hint[:150]}")
    print("\n-- WB --")
    for r in wb_results:
        status = "OK" if r["ok"] else "ERR"
        hint = r.get("body", "") if r["ok"] else (r.get("resp_body") or r.get("err", ""))[:150]
        print(f"  [{status}] {r['label']:40s} {hint[:150]}")


if __name__ == "__main__":
    asyncio.run(main())
