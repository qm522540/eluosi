"""ROI 异常检测任务

每30分钟检查一次各店铺的广告ROI，
当ACOS超过阈值或ROAS过低时触发告警通知。

阈值规则：
- ACOS > 30% → 警告
- ACOS > 50% → 严重
- ROAS < 2.0 → 警告
- 花费 > 日预算80% 且 ROAS < 1.5 → 严重
"""

from datetime import datetime, date, timedelta, timezone

from app.utils.moscow_time import moscow_today
from decimal import Decimal

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models.shop import Shop
from app.models.ad import AdCampaign, AdStat
from app.models.notification import Notification
from app.models.task_log import TaskLog
from app.utils.logger import setup_logger

logger = setup_logger("tasks.roi_alert")

# 告警阈值（默认值，可通过API动态修改）
from app.services.ad.service import _alert_config


def _get_threshold(key, default):
    return _alert_config.get(key, default)


@celery_app.task(
    name="app.tasks.roi_alert.check_roi_anomaly",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def check_roi_anomaly(self):
    """检查所有店铺的ROI异常

    检查维度：
    1. 今日各campaign的ACOS是否超标
    2. 今日各campaign的ROAS是否过低
    3. 花费是否即将超过日预算
    """
    db = SessionLocal()
    log_id = None

    try:
        task_log = TaskLog(
            task_name="check_roi_anomaly",
            celery_task_id=self.request.id,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        db.add(task_log)
        db.commit()
        db.refresh(task_log)
        log_id = task_log.id

        today = moscow_today()
        alerts_generated = 0

        # 获取所有active店铺
        shops = db.query(Shop).filter(Shop.status == "active").all()

        for shop in shops:
            # 获取今日各campaign的汇总统计
            campaigns = db.query(AdCampaign).filter(
                AdCampaign.shop_id == shop.id,
                AdCampaign.tenant_id == shop.tenant_id,
                AdCampaign.status == "active",
            ).all()

            for campaign in campaigns:
                # 汇总今日该campaign的统计
                stats = db.query(AdStat).filter(
                    AdStat.campaign_id == campaign.id,
                    AdStat.stat_date == today,
                ).all()

                if not stats:
                    continue

                total_spend = sum(float(s.spend) for s in stats)
                total_revenue = sum(float(s.revenue) for s in stats)
                total_orders = sum(s.orders for s in stats)

                if total_spend <= 0:
                    continue

                acos = (total_spend / total_revenue * 100) if total_revenue > 0 else 999
                roas = (total_revenue / total_spend) if total_spend > 0 else 0

                alerts = []

                acos_critical = _get_threshold("acos_critical", 50.0)
                acos_warning = _get_threshold("acos_warning", 30.0)
                roas_warning = _get_threshold("roas_warning", 2.0)
                budget_threshold = _get_threshold("budget_usage_threshold", 0.8)
                roas_critical_budget = _get_threshold("roas_critical_with_budget", 1.5)

                # 检查ACOS
                if acos > acos_critical:
                    alerts.append(
                        f"[严重] ACOS={acos:.1f}% (阈值{acos_critical}%)"
                    )
                elif acos > acos_warning:
                    alerts.append(
                        f"[警告] ACOS={acos:.1f}% (阈值{acos_warning}%)"
                    )

                # 检查ROAS
                if roas < roas_warning:
                    alerts.append(f"[警告] ROAS={roas:.2f} (阈值{roas_warning})")

                # 检查预算消耗
                daily_budget = float(campaign.daily_budget) if campaign.daily_budget else 0
                if daily_budget > 0:
                    budget_usage = total_spend / daily_budget
                    if budget_usage > budget_threshold and roas < roas_critical_budget:
                        alerts.append(
                            f"[严重] 预算已用{budget_usage:.0%}，ROAS仅{roas:.2f}"
                        )

                # 生成告警通知
                if alerts:
                    alert_content = (
                        f"店铺: {shop.name} ({shop.platform})\n"
                        f"活动: {campaign.name}\n"
                        f"今日花费: {total_spend:.2f} RUB\n"
                        f"今日收入: {total_revenue:.2f} RUB\n"
                        f"订单数: {total_orders}\n"
                        f"异常项:\n" + "\n".join(f"  - {a}" for a in alerts)
                    )

                    notification = Notification(
                        tenant_id=shop.tenant_id,
                        notification_type="roi_alert",
                        title=f"ROI异常: {campaign.name}",
                        content=alert_content,
                        channel="both",
                        sent_at=datetime.now(timezone.utc),
                    )
                    db.add(notification)
                    alerts_generated += 1

                    logger.warning(
                        f"ROI告警: shop={shop.name}, campaign={campaign.name}, "
                        f"ACOS={acos:.1f}%, ROAS={roas:.2f}"
                    )

        db.commit()

        result = {
            "shops_checked": len(shops),
            "alerts_generated": alerts_generated,
            "check_date": today.isoformat(),
        }

        task_log.status = "success"
        task_log.result = result
        task_log.finished_at = datetime.now(timezone.utc)
        if task_log.started_at:
            task_log.duration_ms = int(
                (task_log.finished_at - task_log.started_at).total_seconds() * 1000
            )
        db.commit()

        logger.info(f"ROI异常检测完成: {result}")
        return result

    except Exception as e:
        logger.error(f"ROI异常检测任务失败: {e}")
        if log_id:
            task_log = db.query(TaskLog).filter(TaskLog.id == log_id).first()
            if task_log:
                task_log.status = "failed"
                task_log.error_message = str(e)[:2000]
                task_log.finished_at = datetime.now(timezone.utc)
                db.commit()
        db.rollback()
        raise self.retry(exc=e)

    finally:
        db.close()
