"""广告自动化规则执行任务

广告数据采集已由 smart_sync / bid-management-hourly 等新路径替代，
本文件仅保留 run_automation_rules 自动化规则执行任务。

已删除的旧任务（2026-04-16 清理）：
- fetch_wb_ad_stats
- fetch_ozon_ad_stats
- fetch_yandex_ad_stats
- _upsert_campaign / _upsert_stat / _fetch_single_*_shop
"""

import asyncio
from datetime import datetime, timezone

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.utils.logger import setup_logger

logger = setup_logger("tasks.ad")


def _run_async(coro):
    """在同步Celery任务中执行异步代码"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ==================== 自动化规则执行 ====================

@celery_app.task(
    name="app.tasks.ad_tasks.run_automation_rules",
    bind=True,
    max_retries=1,
    default_retry_delay=60,
)
def run_automation_rules(self):
    """执行所有租户的广告自动化规则"""
    db = SessionLocal()
    try:
        from app.models.ad import AdAutomationRule
        from app.services.ad.service import execute_automation_rules

        # 获取所有有启用规则的租户
        tenant_ids = [row[0] for row in db.query(
            AdAutomationRule.tenant_id
        ).filter(
            AdAutomationRule.enabled == 1
        ).distinct().all()]

        results = {}
        for tid in tenant_ids:
            result = _run_async(execute_automation_rules(db, tid))
            results[tid] = result.get("data", {})
            logger.info(f"租户 {tid} 自动化规则执行完成: {result.get('data', {}).get('rules_checked', 0)} 条规则")

        return {"tenants_processed": len(tenant_ids), "results": results}
    except Exception as e:
        logger.error(f"自动化规则执行任务异常: {e}")
        raise self.retry(exc=e)
    finally:
        db.close()
