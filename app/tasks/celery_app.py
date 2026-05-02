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
        "app.tasks.ad_auto_exclude_task",
        "app.tasks.ozon_product_queries_task",
        "app.tasks.wb_search_texts_task",
        "app.tasks.cluster_oracle_sync",
        "app.tasks.seo_engine_task",
        "app.tasks.manual_trigger_task",
        "app.tasks.clone_tasks",
    ],
)

# 定时任务调度表
celery_app.conf.beat_schedule = {
    # 每日数据同步：调 wb_smart_sync + ozon_smart_sync 拉昨日 ad_stats
    # hook 接入 (老张 2026-04-28): is_data_source_enabled(wb_orders/ozon_orders) +
    # record_sync_run(...) 在 daily_sync_task.py shop 循环里
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
    # hook 接入: is_data_source_enabled(wb_bid_management/ozon_bid_management)
    "bid-management-hourly": {
        "task": "app.tasks.bid_management.run_bid_management",
        "schedule": crontab(minute=5),
    },
    # 关键词统计每日增量拉取（莫斯科凌晨3点 = UTC 0:00）
    # hook 接入: is_data_source_enabled(wb_keyword_stats)
    "keyword-stats-daily": {
        "task": "app.tasks.keyword_stats_task.sync_keyword_stats",
        "schedule": crontab(hour=0, minute=0),
    },
    # 活动级自动屏蔽托管（莫斯科凌晨4:30 = UTC 1:30）
    # hook 接入: is_data_source_enabled(wb_ad_auto_exclude)
    "ad-auto-exclude-daily": {
        "task": "app.tasks.ad_auto_exclude_task.auto_exclude_keywords",
        "schedule": crontab(hour=1, minute=30),
    },
    # Ozon SKU × 搜索词同步（莫斯科凌晨5:30 = UTC 2:30，错开自动屏蔽）
    "ozon-product-queries-daily": {
        "task": "app.tasks.ozon_product_queries_task.sync_ozon_product_queries",
        "schedule": crontab(hour=2, minute=30),
    },
    # SEO 候选池引擎每日刷新（MSK 05:00，错开 Ozon 02:30 + WB 04:00 之后）
    # 纯本地 SQL,不调外部 API,无 quota 消耗;让候选池跟最新 psq + ad_stats 同步,
    # 修跨店召回时间错配问题(用户已踩 3 次)。单店 ~1.5s 全店 < 30s。
    "seo-engine-daily": {
        "task": "app.tasks.seo_engine_task.refresh_all_shops_candidates",
        "schedule": crontab(hour=5, minute=0),
    },
    # WB SKU × 搜索词同步（搜索词洞察，MSK 04:00 触发，需 Jam 订阅）
    # Celery timezone=Europe/Moscow → crontab(hour=X) 按 MSK 直解 = MSK X:00
    # 选 MSK 04:00 错开 Ozon 的 02:30；单店 609 nmIds ~3min（批量 50 + 15s sleep）
    # hook 接入: is_data_source_enabled(wb_search_texts) + shop=1 在 DB 里
    # 预过滤 enabled=0 (Shario 无 Jam 订阅,避免每天空转一次 401)
    "wb-search-texts-daily": {
        "task": "app.tasks.wb_search_texts_task.sync_wb_search_texts",
        "schedule": crontab(hour=4, minute=0),
    },
    # 店铺克隆每日扫描 (MSK 03:30) — 扫所有 is_active=1 任务, 包含 follow_price_change 跟价
    # 详见 docs/api/store_clone.md §6.1
    "clone-daily-scan": {
        "task": "app.tasks.clone_tasks.daily_scan_all_tasks",
        "schedule": crontab(hour=3, minute=30),
    },
    # 店铺克隆已批准的 pending 异步上架 (每 5 分钟扫一次 status='approved')
    # 详见 docs/api/store_clone.md §6.2
    "clone-publish-pending": {
        "task": "app.tasks.clone_tasks.publish_approved_pending",
        "schedule": crontab(minute="*/5"),
    },
    # WB 顶级搜索集群 oracle 同步 — 2026-04-23 证实 WB cmp API 做了 IP 绑定，
    # 从服务器调会 401（JWT 只在用户浏览器 IP 下有效）。暂停定时，只保留 task
    # 定义作为未来使用（若 WB 改策略或用户提供本地 agent）。
    # "cluster-oracle-sync-daily": {
    #     "task": "app.tasks.cluster_oracle_sync.sync_wb_cluster_oracle",
    #     "schedule": crontab(hour=3, minute=30),
    # },
}
