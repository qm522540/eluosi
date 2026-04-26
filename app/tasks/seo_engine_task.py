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
from app.services.seo.service import analyze_paid_to_organic
from app.utils.logger import setup_logger

logger = setup_logger("tasks.seo_engine")


@celery_app.task(
    name="app.tasks.seo_engine_task.refresh_all_shops_candidates",
    bind=True, max_retries=1, default_retry_delay=600,
)
def refresh_all_shops_candidates(self):
    """遍历所有 active WB+Ozon 店,逐一刷 SEO 候选池"""
    db = SessionLocal()
    try:
        shops = db.query(Shop).filter(
            Shop.platform.in_(["wb", "ozon"]),
            Shop.status == "active",
        ).all()
        results = []
        for shop in shops:
            try:
                r = analyze_paid_to_organic(
                    db, tenant_id=shop.tenant_id, shop=shop,
                    days=30, roas_threshold=2.0, min_orders=1,
                )
                db.commit()
                data = r.get("data") or {}
                results.append({
                    "shop_id": shop.id, "shop_name": shop.name,
                    "candidates": data.get("candidates", 0),
                    "written": data.get("written", 0),
                })
                logger.info(
                    f"shop_id={shop.id} {shop.name} 候选池刷新完成: "
                    f"candidates={data.get('candidates', 0)} written={data.get('written', 0)}"
                )
            except Exception as e:
                db.rollback()
                logger.error(f"shop_id={shop.id} {shop.name} 候选池刷新失败: {e}")
                results.append({"shop_id": shop.id, "error": str(e)[:200]})
        logger.info(f"SEO 引擎每日刷新完成,共处理 {len(shops)} 店")
        return {"shops": len(shops), "results": results}
    finally:
        db.close()
