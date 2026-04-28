"""数据源静态目录 — 系统支持的所有数据源元数据

每个 source_key 对应一个 celery beat task / 手动同步入口。
新增数据源时在这里加一条 + 在对应 beat task 加 is_data_source_enabled() hook。

字段:
- key: 数据源唯一标识 (DB 里 source_key 列), 跟 task name 无关
- label: 给用户看的中文名
- category: "api" (调外部平台 API,受店铺 API 总开关 + 单源开关双层控制) / "local" (纯 SQL,只受单源开关控制)
- platform: "wb" / "ozon" / "shared" (跨平台/共享类如 SEO 引擎)
- schedule_desc: 周期描述 (展示用)
- task_name: celery task 完整 name (供后端 task hook 读 enabled 状态用)
- manual_only: True = 没定时任务,只能手动触发 (如 WB 搜索词洞察当前是)
- depends: 该数据源依赖的订阅/认证 (展示用)
"""

DATA_SOURCES = {
    # ============ WB API 类 ============
    "wb_orders": {
        "label": "WB 订单同步",
        "category": "api",
        "platform": "wb",
        "schedule_desc": "每日 02:00 (MSK)",
        "task_name": "app.tasks.daily_sync_task.daily_sync_all_shops",
        "depends": ["seller token"],
    },
    "wb_bid_management": {
        "label": "WB 出价管理",
        "category": "api",
        "platform": "wb",
        "schedule_desc": "每小时 :05",
        "task_name": "app.tasks.bid_management.run_bid_management",
        "depends": ["seller token", "广告权限"],
    },
    "wb_keyword_stats": {
        "label": "WB 关键词统计",
        "category": "api",
        "platform": "wb",
        "schedule_desc": "每日 00:00 (MSK)",
        "task_name": "app.tasks.keyword_stats_task.sync_keyword_stats",
        "depends": ["seller token", "广告权限"],
    },
    "wb_ad_auto_exclude": {
        "label": "WB 自动屏蔽托管",
        "category": "api",
        "platform": "wb",
        "schedule_desc": "每日 04:30 (MSK)",
        "task_name": "app.tasks.ad_auto_exclude_task.auto_exclude_keywords",
        "depends": ["seller token", "广告权限"],
    },
    "wb_search_texts": {
        "label": "WB 搜索词洞察",
        "category": "api",
        "platform": "wb",
        "schedule_desc": "每日 04:00 (MSK)",
        "task_name": "app.tasks.wb_search_texts_task.sync_wb_search_texts",
        "depends": ["Jam 订阅"],
    },
    # ============ Ozon API 类 ============
    "ozon_orders": {
        "label": "Ozon 订单同步",
        "category": "api",
        "platform": "ozon",
        "schedule_desc": "每日 02:00 (MSK,与 WB 同任务)",
        "task_name": "app.tasks.daily_sync_task.daily_sync_all_shops",
        "depends": ["seller token"],
    },
    "ozon_search_texts": {
        "label": "Ozon 搜索词洞察",
        "category": "api",
        "platform": "ozon",
        "schedule_desc": "每日 05:30 (MSK)",
        "task_name": "app.tasks.ozon_product_queries_task.sync_ozon_product_queries",
        "depends": ["Premium 订阅"],
    },
    # ============ 本地类 (跨店共享, 不受店铺 API 总开关影响) ============
    "seo_engine": {
        "label": "SEO 候选池引擎",
        "category": "local",
        "platform": "shared",
        "schedule_desc": "每日 05:00 (MSK)",
        "task_name": "app.tasks.seo_engine_task.refresh_all_shops_candidates",
        "depends": [],
    },
}


def is_api_source(source_key: str) -> bool:
    """是否为 API 类数据源 (受店铺 API 总开关影响)。"""
    src = DATA_SOURCES.get(source_key)
    return bool(src and src.get("category") == "api")


def is_shared_source(source_key: str) -> bool:
    """是否为跨店共享数据源 (不属于任何特定 shop)。"""
    src = DATA_SOURCES.get(source_key)
    return bool(src and src.get("platform") == "shared")


def get_sources_for_platform(platform: str) -> list:
    """返回指定平台 (wb/ozon) 的所有 source_key + meta。"""
    out = []
    for k, v in DATA_SOURCES.items():
        if v.get("platform") in (platform, "shared"):
            out.append({"key": k, **v})
    return out
