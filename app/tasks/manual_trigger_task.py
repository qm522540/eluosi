"""数据源管理 Tab "手动更新" 按钮统一入口

每个数据源后面那个"更新"按钮 → POST /data-sources/shop/{id}/{source_key}/sync
→ celery.send_task → 本 task 内部按 source_key 分发到具体同步函数。

设计:
- 顶部 hook 检查 (data_source_config.enabled + shops.api_enabled)
- 末尾 record_sync_run (UI "最近同步" 列 + task_logs 全系统观测)
- 异步派发,前端立刻拿 task_id,看 "最近同步" 列查结果

每个分支按统一模板:
1. is_data_source_enabled 检查 → False 则 record skipped + return
2. 跑业务函数 (asyncio.run_until_complete 包装 async 函数)
3. record_sync_run 写状态
"""

from __future__ import annotations

import asyncio
from typing import Optional

from app.database import SessionLocal
from app.models.shop import Shop
from app.services.data_source.catalog import DATA_SOURCES
from app.services.data_source.service import is_data_source_enabled, record_sync_run
from app.tasks.celery_app import celery_app
from app.utils.logger import setup_logger
from app.utils.moscow_time import utc_now_naive

logger = setup_logger("tasks.manual_trigger")


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _wrap(db, tenant_id: int, shop_id: Optional[int], source_key: str, work_fn) -> dict:
    """统一: hook → 跑 work_fn → record_sync_run。

    work_fn 返回 dict, 可包含 _rows / _msg 元数据 (不会传给前端):
        return {"_rows": 123, "_msg": "...", "其他业务返回": ...}
    """
    enabled, reason = is_data_source_enabled(db, tenant_id, shop_id, source_key)
    if not enabled:
        record_sync_run(db, tenant_id, shop_id, source_key,
                       status="skipped", msg=reason or "")
        return {"skipped": reason}

    t0 = utc_now_naive()
    try:
        result = work_fn() or {}
        rows = int(result.pop("_rows", 0) or 0) if isinstance(result, dict) else 0
        msg = str(result.pop("_msg", ""))[:500] if isinstance(result, dict) else ""
        dur_ms = int((utc_now_naive() - t0).total_seconds() * 1000)
        record_sync_run(db, tenant_id, shop_id, source_key,
                       status="success", rows=rows, duration_ms=dur_ms, msg=msg)
        return {"ok": True, "rows": rows, **(result if isinstance(result, dict) else {})}
    except Exception as e:
        dur_ms = int((utc_now_naive() - t0).total_seconds() * 1000)
        record_sync_run(db, tenant_id, shop_id, source_key,
                       status="failed", msg=str(e)[:500], duration_ms=dur_ms)
        logger.error(f"manual_trigger {source_key} shop={shop_id} 失败: {e}", exc_info=True)
        raise


@celery_app.task(
    name="app.tasks.manual_trigger_task.manual_trigger_one",
    bind=True, max_retries=0,
)
def manual_trigger_one(self, shop_id: int, tenant_id: int, source_key: str) -> dict:
    """单店单源手动触发统一入口"""
    if source_key not in DATA_SOURCES:
        return {"error": f"未知数据源: {source_key}"}

    db = SessionLocal()
    try:
        shop = db.query(Shop).filter(
            Shop.id == shop_id, Shop.tenant_id == tenant_id,
        ).first()
        if not shop:
            return {"error": "店铺不存在或不属于当前租户"}

        # ==================== 订单同步 (ad_stats) ====================
        if source_key in ("wb_orders", "ozon_orders"):
            from app.services.data.wb_stats_collector import smart_sync as wb_sync
            from app.services.data.ozon_stats_collector import smart_sync as ozon_sync
            fn = wb_sync if source_key == "wb_orders" else ozon_sync
            def work():
                r = _run_async(fn(db, shop_id, tenant_id))
                return {"_rows": r.get("synced", 0),
                        "_msg": f"date_range={r.get('date_from')}~{r.get('date_to')}"}
            return _wrap(db, tenant_id, shop_id, source_key, work)

        # ==================== 商品同步 ====================
        if source_key in ("wb_products", "ozon_products"):
            # sync_products_from_platform 内部已含 hook + record_sync_run,
            # 这里的 _wrap 也会 record 一次 — 双重记录但 UPSERT 幂等,task_logs 多 1 行而已
            # 不死循环:外层 record 先,内层 sync_products_from_platform 自己再 record (覆盖最新)
            from app.services.product.service import sync_products_from_platform
            def work():
                r = sync_products_from_platform(db, shop_id, tenant_id) or {}
                data = (r.get("data") or {}) if isinstance(r, dict) else {}
                return {"_rows": data.get("synced", 0),
                        "_msg": str(r.get("msg", ""))[:500]}
            return _wrap(db, tenant_id, shop_id, source_key, work)

        # ==================== 推广活动同步 ====================
        if source_key in ("wb_campaigns", "ozon_campaigns"):
            from app.api.v1.ads import _sync_wb_campaigns, _sync_ozon_campaigns
            fn = _sync_ozon_campaigns if source_key == "ozon_campaigns" else _sync_wb_campaigns
            def work():
                _, updated = _run_async(fn(db, shop))
                return {"_rows": int(updated or 0),
                        "_msg": f"updated_campaigns={updated}"}
            return _wrap(db, tenant_id, shop_id, source_key, work)

        # ==================== 搜索词洞察 (WB / Ozon) ====================
        if source_key in ("wb_search_texts", "ozon_search_texts"):
            from app.services.search_insights.service import refresh_shop
            def work():
                # days=7 默认 — 跟前端 search-insights/refresh 默认一致
                r = _run_async(refresh_shop(db, tenant_id, shop, days=7))
                code = r.get("code", 0)
                data = r.get("data") or {}
                if code == 93001:
                    raise Exception("订阅未开通 (Jam/Premium)")
                if code != 0:
                    raise Exception(f"refresh 失败 code={code} {r.get('msg', '')}")
                return {"_rows": int(data.get("synced_queries", 0) or 0),
                        "_msg": f"range={data.get('date_range')}"}
            return _wrap(db, tenant_id, shop_id, source_key, work)

        # ==================== 关键词统计 ====================
        if source_key == "wb_keyword_stats":
            from datetime import timedelta
            from app.utils.moscow_time import moscow_today
            from app.tasks.keyword_stats_task import _sync_wb_shop_keywords
            def work():
                yesterday = (moscow_today() - timedelta(days=1)).isoformat()
                r = _run_async(_sync_wb_shop_keywords(db, shop, yesterday, yesterday))
                return {"_rows": int(r.get("inserted", 0) or 0),
                        "_msg": f"campaigns={r.get('campaigns', 0)}"}
            return _wrap(db, tenant_id, shop_id, source_key, work)

        # ==================== 出价管理 ====================
        if source_key in ("wb_bid_management", "ozon_bid_management"):
            from app.tasks.bid_management import _process_shop
            def work():
                r = _process_shop(db, shop) or {}
                return {"_msg": str(r.get("mode", ""))[:500]}
            return _wrap(db, tenant_id, shop_id, source_key, work)

        # ==================== 自动屏蔽托管 ====================
        if source_key == "wb_ad_auto_exclude":
            return {"error": "自动屏蔽暂不支持单店手动触发, 请用广告管理页活动级'立即跑一次'按钮按活动触发"}

        # ==================== SEO 候选池引擎 (共享, 单店触发只刷该店) ====================
        if source_key == "seo_engine":
            from app.services.seo.service import analyze_paid_to_organic
            def work():
                r = analyze_paid_to_organic(
                    db, tenant_id=tenant_id, shop=shop,
                    days=30, roas_threshold=2.0, min_orders=1,
                )
                db.commit()
                data = (r.get("data") or {}) if isinstance(r, dict) else {}
                return {"_rows": int(data.get("written", 0) or 0),
                        "_msg": f"shop={shop_id} written={data.get('written', 0)}"}
            # seo_engine 是共享 source: shop_id=None
            return _wrap(db, tenant_id, None, source_key, work)

        return {"error": f"source_key {source_key} 暂不支持手动触发"}

    finally:
        db.close()
