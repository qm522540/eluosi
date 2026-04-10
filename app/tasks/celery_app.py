from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "ecommerce_ai",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Moscow",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    include=[
        "app.tasks.ad_tasks",
        "app.tasks.daily_stats",
        "app.tasks.report_tasks",
        "app.tasks.roi_alert",
        "app.tasks.ai_pricing_task",
        "app.tasks.daily_sync_task",
    ],
)

# 定时任务调度表
celery_app.conf.beat_schedule = {
    # 每日数据同步：莫斯科凌晨2点拉取所有Ozon店铺昨日数据
    "daily-sync-all-shops": {
        "task": "app.tasks.daily_sync_task.daily_sync_all_shops",
        "schedule": crontab(hour=2, minute=0),
    },
    # 日报：莫斯科早8点发送
    "daily-report": {
        "task": "app.tasks.report_tasks.generate_daily_report",
        "schedule": crontab(hour=8, minute=0),
    },
    # ROI异常检测
    "roi-alert-check": {
        "task": "app.tasks.roi_alert.check_roi_anomaly",
        "schedule": crontab(minute="*/30"),
    },
    # 自动化规则执行（每小时）
    "ad-automation-rules": {
        "task": "app.tasks.ad_tasks.run_automation_rules",
        "schedule": crontab(minute=25),
    },
    # AI智能调价（每10分钟检查，由莫斯科时段策略决定是否执行）
    "ai-pricing-smart-check": {
        "task": "app.tasks.ai_pricing_task.check_and_run_ai_pricing",
        "schedule": crontab(minute="*/10"),
    },
}
