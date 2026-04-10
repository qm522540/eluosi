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
    timezone="Asia/Shanghai",
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
    ],
)

# 定时任务调度表
celery_app.conf.beat_schedule = {
    # 每小时拉取广告数据
    "fetch-wb-ads-hourly": {
        "task": "app.tasks.ad_tasks.fetch_wb_ad_stats",
        "schedule": crontab(minute=5),  # 每小时05分
    },
    "fetch-ozon-ads-hourly": {
        "task": "app.tasks.ad_tasks.fetch_ozon_ad_stats",
        "schedule": crontab(minute=10),
    },
    "fetch-yandex-ads-hourly": {
        "task": "app.tasks.ad_tasks.fetch_yandex_ad_stats",
        "schedule": crontab(minute=15),
    },
    # 每日统计
    "daily-wb-stats": {
        "task": "app.tasks.daily_stats.fetch_wb_daily",
        "schedule": crontab(hour=0, minute=10),
    },
    "daily-ozon-stats": {
        "task": "app.tasks.daily_stats.fetch_ozon_daily",
        "schedule": crontab(hour=1, minute=0),
    },
    "daily-yandex-stats": {
        "task": "app.tasks.daily_stats.fetch_yandex_daily",
        "schedule": crontab(hour=2, minute=0),
    },
    # 日报
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
