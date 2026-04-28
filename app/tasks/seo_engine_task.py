"""SEO 候选池引擎每日刷新

每日 MSK 05:00（错开 Ozon psq 同步 02:30 + WB 04:00 之后）扫描所有 active
WB+Ozon 店,逐一调 analyze_paid_to_organic 把候选池跟最新 ad_stats /
product_search_queries 数据对齐。

核心问题这个 beat 在解决:
- analyze_paid_to_organic 是纯本地 SQL JOIN,不调外部 API,零 quota 消耗
- 但 Step G 跨店召回依赖 product_search_queries 表的最新数据
- psq 表是 02:30 / 04:00 的 beat 自动同步,如果不刷候选池,新数据永远不会
  反哺到本店候选池(用户已踩 3 次"PT-N0017 在 WB-Pt.Gril 看不到 Ozon 同款词")

任务幂等:UPSERT seo_keyword_candidates,失败也只是不更新候选池,无副作用。
"""

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models.shop import Shop
from app.services.data_source.service import is_data_source_enabled, record_sync_run
from app.services.seo.service import analyze_paid_to_organic
from app.utils.logger import setup_logger
from app.utils.moscow_time import utc_now_naive

logger = setup_logger("tasks.seo_engine")


@celery_app.task(
    name="app.tasks.seo_engine_task.refresh_all_shops_candidates",
    bind=True, max_retries=1, default_retry_delay=600,
)
def refresh_all_shops_candidates(self):
    """遍历所有 active WB+Ozon 店,逐一刷 SEO 候选池

    seo_engine 是跨店共享数据源 (data_source_config.shop_id=0),
    但 tenant 维度仍独立 — 不同租户可独立暂停 SEO 引擎。
    """
    db = SessionLocal()
    try:
        t0 = utc_now_naive()
        shops = db.query(Shop).filter(
            Shop.platform.in_(["wb", "ozon"]),
            Shop.status == "active",
        ).all()
        results = []
        total_written = 0
        had_error = False
        # tenant 级 hook 缓存 + per-tenant 累计 (record_sync_run 按 tenant 各写一行)
        tenant_gate = {}      # tenant_id -> (enabled, skip_reason)
        tenant_stat = {}      # tenant_id -> {"written": int, "had_error": bool, "shops": int}

        for shop in shops:
            tid = shop.tenant_id
            # Per-tenant hook (共享数据源,每个 tenant 一次决策)
            if tid not in tenant_gate:
                tenant_gate[tid] = is_data_source_enabled(
                    db, tenant_id=tid, shop_id=None, source_key="seo_engine",
                )
                tenant_stat[tid] = {"written": 0, "had_error": False, "shops": 0}
            enabled, skip_reason = tenant_gate[tid]
            if not enabled:
                logger.info(f"tenant={tid} shop_id={shop.id} seo_engine 暂停: {skip_reason}")
                results.append({"shop_id": shop.id, "skipped": skip_reason})
                continue
            tenant_stat[tid]["shops"] += 1
            try:
                r = analyze_paid_to_organic(
                    db, tenant_id=shop.tenant_id, shop=shop,
                    days=30, roas_threshold=2.0, min_orders=1,
                )
                db.commit()
                data = r.get("data") or {}
                written = int(data.get("written", 0) or 0)
                total_written += written
                tenant_stat[tid]["written"] += written
                results.append({
                    "shop_id": shop.id, "shop_name": shop.name,
                    "candidates": data.get("candidates", 0),
                    "written": written,
                })
                logger.info(
                    f"shop_id={shop.id} {shop.name} 候选池刷新完成: "
                    f"candidates={data.get('candidates', 0)} written={written}"
                )
            except Exception as e:
                db.rollback()
                had_error = True
                tenant_stat[tid]["had_error"] = True
                logger.error(f"shop_id={shop.id} {shop.name} 候选池刷新失败: {e}")
                results.append({"shop_id": shop.id, "error": str(e)[:200]})

        # 收尾: 每个 (允许跑过的) tenant 各 record 一行 (共享数据源 shop_id=None)
        dur_ms = int((utc_now_naive() - t0).total_seconds() * 1000)
        for tid, st in tenant_stat.items():
            enabled, _ = tenant_gate[tid]
            if not enabled:
                # skipped tenant 已经在循环里 record 了 (其实没有 — 这里补一次)
                record_sync_run(db, tenant_id=tid, shop_id=None, source_key="seo_engine",
                               status="skipped", msg=tenant_gate[tid][1] or "")
                continue
            rec_status = "partial" if st["had_error"] else "success"
            record_sync_run(db, tenant_id=tid, shop_id=None, source_key="seo_engine",
                           status=rec_status, rows=st["written"], duration_ms=dur_ms,
                           msg=f"shops={st['shops']} written={st['written']}")
        logger.info(f"SEO 引擎每日刷新完成,共处理 {len(shops)} 店,total_written={total_written}")
        return {"shops": len(shops), "results": results, "total_written": total_written}
    finally:
        db.close()
