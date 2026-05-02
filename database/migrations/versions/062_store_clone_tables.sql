-- 062_store_clone_tables.sql
-- 店铺克隆 — 4 张新表
--
-- 目的: 实现"A 店自动跟踪 B 店上新 → 抓取改写 → 入待审核 → 用户批准 → 推 A 上架"闭环
--
-- 表清单:
-- 1. clone_tasks            克隆任务 (A ← B 关系 + 配置 + 运行状态)
-- 2. clone_pending_products 待审核商品队列 (核心交互区)
-- 3. clone_logs             克隆日志 (扫描/审核/发布/跟价)
-- 4. clone_published_links  已发布关系 (追溯 + follow_price_change 跟价用)
--
-- 类型惯例 (老张 review 抓出的关键): 所有 id / tenant_id / shop_id / task_id / listing_id / user_id
-- 用 BIGINT UNSIGNED, 与现有核心表 (platform_listings/shops/products/tenants/users/task_logs) 对齐。
-- 060 data_source_config 用 BIGINT 不带 UNSIGNED 是历史例外, 不作惯例参考。
-- JOIN platform_listings.clone_task_id ↔ clone_tasks.id 必须类型一致, 否则隐式转换 + 索引失效。
--
-- 规则 1 多租户: 所有表第一列 tenant_id, 业务 SQL where 必须显式 AND tenant_id
-- 规则 6 时间: created_at / updated_at 用 CURRENT_TIMESTAMP 仅占位,
--             业务字段 (last_check_at / detected_at / reviewed_at / published_at / last_synced_at)
--             必须由 service 层显式传 utc_now_naive()
-- 关联文档: docs/api/store_clone.md §3
-- 错误码段: 95xxx (定义在 app/utils/errors.py)
--
-- Phase 2 已知 schema 改造点 (Phase 1 不影响):
-- - clone_tasks 的 uk_target_source 在 source_shop_id IS NULL 时 MySQL 允许多 NULL,
--   Phase 2 公开 API 模式启用时需改造 (generated column 或 NOT NULL DEFAULT '');
--   详见 docs/api/store_clone.md §3.2 注意块。

-- ==================== 1. clone_tasks ====================

CREATE TABLE IF NOT EXISTS clone_tasks (
    id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    tenant_id BIGINT UNSIGNED NOT NULL,
    target_shop_id BIGINT UNSIGNED NOT NULL
        COMMENT 'A 店 (落地店); 路由层 get_owned_shop 守卫归属',
    source_shop_id BIGINT UNSIGNED DEFAULT NULL
        COMMENT 'B 店 (被跟踪店); Phase 1 必填, Phase 2 公开 API 模式可空',
    source_type ENUM('seller_api','public_api') NOT NULL DEFAULT 'seller_api'
        COMMENT '数据来源类型; Phase 1 仅 seller_api',

    -- Phase 2 公开 API 留口 (Phase 1 全 NULL)
    source_platform VARCHAR(20) DEFAULT NULL
        COMMENT 'Phase 2: 公开 API 时记录 B 平台 (wb/ozon/yandex)',
    source_external_id VARCHAR(200) DEFAULT NULL
        COMMENT 'Phase 2: 竞品 supplier_id / shop_url',
    source_sku_whitelist JSON DEFAULT NULL
        COMMENT 'Phase 2: Ozon 公开 API 模式的手动 SKU 列表',

    is_active TINYINT(1) NOT NULL DEFAULT 0
        COMMENT '0=未启用 (创建后默认), 1=启用 (定时任务会扫到)',

    -- 配置
    title_mode ENUM('original','ai_rewrite') NOT NULL DEFAULT 'original'
        COMMENT '标题处理: 保留原名 / 调 SEO optimize_title 改写',
    desc_mode ENUM('original','ai_rewrite') NOT NULL DEFAULT 'original'
        COMMENT '描述处理: 保留原描述 / 调 SEO generate_description 改写',
    price_mode ENUM('same','adjust_pct') NOT NULL DEFAULT 'same'
        COMMENT '价格策略: 同 B 价 / 按百分比上调下调',
    price_adjust_pct DECIMAL(5,2) DEFAULT NULL
        COMMENT '正数=涨, 负数=跌; price_mode=adjust_pct 时必填, 范围 [-50, 200]',
    default_stock INT NOT NULL DEFAULT 999
        COMMENT 'A 店上架时的默认库存 (B 店库存不复制, A 自治)',
    follow_price_change TINYINT(1) NOT NULL DEFAULT 0
        COMMENT '1 = B 改价后 A 自动跟价 (不走审核, 直接调 A 平台 update_price)',

    -- 类目映射策略
    category_strategy ENUM('same_platform','use_local_map','reject_if_missing')
        NOT NULL DEFAULT 'use_local_map'
        COMMENT '同平台直接复用 / 跨平台走 028 映射库 / 缺失即拒',

    -- 运行状态
    last_check_at DATETIME DEFAULT NULL
        COMMENT '上次扫描时间 (UTC naive); NULL = 未扫描过, 首次取 created_at - 7 days',
    last_found_count INT NOT NULL DEFAULT 0
        COMMENT '上次扫描 B 店返回的商品总数',
    last_publish_count INT NOT NULL DEFAULT 0
        COMMENT '上次扫描入待审条数',
    last_skip_count INT NOT NULL DEFAULT 0
        COMMENT '上次扫描跳过数 (已发布 + 已拒绝 + 类目缺失)',
    last_error_msg VARCHAR(500) DEFAULT NULL
        COMMENT '上次扫描错误 (如 B 店凭证失效)',

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_target_source (tenant_id, target_shop_id, source_shop_id),
    KEY idx_active (tenant_id, is_active),
    KEY idx_target (target_shop_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='店铺克隆任务 (A ← B 关系 + 配置 + 运行状态快照)';


-- ==================== 2. clone_pending_products ====================

CREATE TABLE IF NOT EXISTS clone_pending_products (
    id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    tenant_id BIGINT UNSIGNED NOT NULL,
    task_id BIGINT UNSIGNED NOT NULL
        COMMENT '关联 clone_tasks.id',

    -- 来源
    source_shop_id BIGINT UNSIGNED DEFAULT NULL
        COMMENT 'Phase 1 等于 task.source_shop_id; Phase 2 可空',
    source_platform VARCHAR(20) NOT NULL,
    source_sku_id VARCHAR(100) NOT NULL
        COMMENT 'B 平台 SKU (WB nm_id / Ozon offer_id / Yandex offerId)',

    -- B 商品快照 (抓取瞬间, debug + 用户审核展示用)
    source_snapshot JSON NOT NULL
        COMMENT '完整 ProductSnapshot dict (title/desc/price/stock/images/attrs/raw)',

    -- 应用规则后的 A 商品 payload (供用户审核 + 发布)
    proposed_payload JSON NOT NULL
        COMMENT 'JSON: {title_ru, description_ru, price_rub, stock, images_oss, '
                'platform_category_id, attributes, _ai_rewrite_failed_*}',

    -- 关联 platform_listings 草稿 (AI 改写复用 SEO 接口的锚点)
    draft_listing_id BIGINT UNSIGNED DEFAULT NULL
        COMMENT '关联 platform_listings.id (status=inactive, clone_task_id IS NOT NULL)',

    -- 状态机
    status ENUM('pending','approved','rejected','published','failed')
        NOT NULL DEFAULT 'pending',
    category_mapping_status ENUM('ok','missing','ai_suggested') NOT NULL DEFAULT 'ok'
        COMMENT '类目映射状态 (ai_suggested 给 Phase 2 AI 兜底用, Phase 1 不写入)',
    reject_reason VARCHAR(200) DEFAULT NULL,
    publish_error_msg VARCHAR(500) DEFAULT NULL,

    -- 审计
    detected_at DATETIME NOT NULL
        COMMENT '抓取时间 (UTC naive); service 层 utc_now_naive()',
    reviewed_at DATETIME DEFAULT NULL
        COMMENT '用户 approve / reject / restore 时间',
    reviewed_by BIGINT UNSIGNED DEFAULT NULL
        COMMENT '操作人 user_id',
    published_at DATETIME DEFAULT NULL
        COMMENT 'A 平台上架成功时间',
    target_platform_sku_id VARCHAR(100) DEFAULT NULL
        COMMENT 'A 店上架后的真实 SKU (publish 成功后回填)',

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_task_source_sku (task_id, source_sku_id)
        COMMENT '同任务下同来源 SKU 唯一; 决策 5 永久跳过的物理保障 (重复扫描自然忽略)',
    KEY idx_status (tenant_id, status),
    KEY idx_task_status (task_id, status),
    KEY idx_draft_listing (draft_listing_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='店铺克隆待审核商品队列 (核心交互区, 用户每天打开)';


-- ==================== 3. clone_logs ====================

CREATE TABLE IF NOT EXISTS clone_logs (
    id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    tenant_id BIGINT UNSIGNED NOT NULL,
    task_id BIGINT UNSIGNED DEFAULT NULL
        COMMENT '系统级日志可空, 任务相关必填',
    log_type ENUM('scan','review','publish','price_sync') NOT NULL,
    status ENUM('success','partial','failed','skipped') NOT NULL,
    rows_affected INT NOT NULL DEFAULT 0,
    duration_ms INT DEFAULT NULL,

    -- detail JSON 按 log_type 不同结构 (前端日志页据此渲染):
    --
    -- scan 类型:
    -- {
    --   "found": 120, "new": 3,
    --   "skip_published": 105, "skip_rejected": 12, "skip_category_missing": 0,
    --   "ai_rewrite_total": 3, "ai_rewrite_failed": 0,
    --   "skipped_skus": [
    --     {"sku":"123","reason":"published"},
    --     {"sku":"789","reason":"category_missing","detail":"WB subjectID 8126 未映射"}
    --   ]
    -- }
    --
    -- review 类型 (approve / reject / restore):
    -- { "action": "approve|reject|restore", "pending_id": 101, "reason": "..." }
    --
    -- publish 类型:
    -- { "pending_id": 101, "target_platform_sku_id": "...", "platform_resp": {...} }
    --   失败时含 "error_code" / "error_msg"
    --
    -- price_sync 类型:
    -- { "pending_id": 101, "old_price": 2400, "new_price": 2640, "delta_pct": 10.0 }
    detail JSON DEFAULT NULL,
    error_msg VARCHAR(500) DEFAULT NULL,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    KEY idx_task_type (task_id, log_type, created_at),
    KEY idx_tenant_created (tenant_id, created_at),
    KEY idx_tenant_log_type (tenant_id, log_type, created_at)
        COMMENT 'UI 按租户 + 类型筛日志走此索引 (老张 review 加)'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='店铺克隆日志 (扫描/审核/发布/跟价); detail JSON 按 log_type 多态';


-- ==================== 4. clone_published_links ====================

CREATE TABLE IF NOT EXISTS clone_published_links (
    id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    tenant_id BIGINT UNSIGNED NOT NULL,
    task_id BIGINT UNSIGNED NOT NULL,
    pending_id BIGINT UNSIGNED NOT NULL
        COMMENT '关联 clone_pending_products.id (一一对应)',
    source_platform VARCHAR(20) NOT NULL,
    source_sku_id VARCHAR(100) NOT NULL,
    target_shop_id BIGINT UNSIGNED NOT NULL,
    target_platform_sku_id VARCHAR(100) NOT NULL
        COMMENT 'A 店上架后的真实 SKU',
    target_listing_id BIGINT UNSIGNED DEFAULT NULL
        COMMENT '关联 platform_listings.id (status=active 后)',

    -- 跟价数据 (follow_price_change=1 时维护; source_shop_id 通过 task_id 反查 clone_tasks)
    last_synced_price DECIMAL(10,2) DEFAULT NULL
        COMMENT '上次跟价同步后 A 店当前价格',
    last_synced_at DATETIME DEFAULT NULL
        COMMENT '上次跟价时间 (UTC naive)',

    published_at DATETIME NOT NULL
        COMMENT 'A 平台上架成功时间',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uk_pending (pending_id)
        COMMENT '一条 pending 只能对应一条上架记录',
    KEY idx_task (task_id),
    KEY idx_source (source_platform, source_sku_id),
    KEY idx_target (target_platform_sku_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='店铺克隆已发布关系 (追溯 + follow_price_change 跟价数据源)';
