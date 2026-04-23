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
        "app.tasks.daily_sync_task",
        "app.tasks.bid_management",
        "app.tasks.keyword_stats_task",
        "app.tasks.region_stats_task",
        "app.tasks.ad_auto_exclude_task",
        "app.tasks.ozon_product_queries_task",
        "app.tasks.cluster_oracle_sync",
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
    # ROI异常检测 —— 前端页面已删（小明 a959039），暂停定时调度
    # "roi-alert-check": {
    #     "task": "app.tasks.roi_alert.check_roi_anomaly",
    #     "schedule": crontab(minute="*/30"),
    # },
    # 自动化规则执行 —— 前端页面已删，暂停定时调度
    # "ad-automation-rules": {
    #     "task": "app.tasks.ad_tasks.run_automation_rules",
    #     "schedule": crontab(minute=25),
    # },
    # 出价管理统一入口（莫斯科时间每小时:05触发，分时调价 + AI调价二选一）
    "bid-management-hourly": {
        "task": "app.tasks.bid_management.run_bid_management",
        "schedule": crontab(minute=5),
    },
    # 关键词统计每日增量拉取（莫斯科凌晨3点 = UTC 0:00）
    "keyword-stats-daily": {
        "task": "app.tasks.keyword_stats_task.sync_keyword_stats",
        "schedule": crontab(hour=0, minute=0),
    },
    # 地区销售每日增量拉取（莫斯科凌晨4点 = UTC 1:00）
    "region-stats-daily": {
        "task": "app.tasks.region_stats_task.sync_region_stats",
        "schedule": crontab(hour=1, minute=0),
    },
    # 活动级自动屏蔽托管（莫斯科凌晨4:30 = UTC 1:30，错开 region-stats）
    "ad-auto-exclude-daily": {
        "task": "app.tasks.ad_auto_exclude_task.auto_exclude_keywords",
        "schedule": crontab(hour=1, minute=30),
    },
    # Ozon SKU × 搜索词同步（莫斯科凌晨5:30 = UTC 2:30，错开自动屏蔽）
    "ozon-product-queries-daily": {
        "task": "app.tasks.ozon_product_queries_task.sync_ozon_product_queries",
        "schedule": crontab(hour=2, minute=30),
    },
    # WB 顶级搜索集群 oracle 同步（莫斯科每日 03:30，遍历所有配了 JWT 的 WB 店铺）
    "cluster-oracle-sync-daily": {
        "task": "app.tasks.cluster_oracle_sync.sync_wb_cluster_oracle",
        "schedule": crontab(hour=3, minute=30),
    },
}
