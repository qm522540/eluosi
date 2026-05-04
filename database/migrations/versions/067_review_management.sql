-- 067_review_management.sql
-- 2026-05-04 老张 — 评价管理模块新增 3 张表
-- 业务: 拉买家评价 → AI 翻译俄→中 → AI 起草友好+温暖回复 → 人工编辑/重生成 → 一键发送
-- 关联: app/services/reviews/ + app/models/review.py + app/api/v1/reviews.py
-- 平台: WB Feedbacks API + Ozon Review API (Premium 订阅)
-- 自动回复: 仅 4-5 星走自动 (差评强制人工), 每店独立开关 (shop_review_settings)

-- ==================== 1. 评价主表 ====================
CREATE TABLE IF NOT EXISTS `shop_reviews` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `shop_id` BIGINT UNSIGNED NOT NULL,
    `platform` ENUM('wb', 'ozon') NOT NULL,
    `platform_review_id` VARCHAR(64) NOT NULL
        COMMENT 'WB feedback.id / Ozon review.id (UUID)',
    `rating` TINYINT UNSIGNED NOT NULL
        COMMENT '1-5 星',
    `content_ru` TEXT NOT NULL
        COMMENT '买家俄语原文 (WB text / Ozon comment)',
    `content_zh` TEXT NULL
        COMMENT 'AI 中文翻译 (复用 ru_zh_dict 缓存, 异步填)',
    `sentiment` ENUM('positive', 'neutral', 'negative', 'unknown') NOT NULL DEFAULT 'unknown'
        COMMENT 'AI 情感分析: rating + 内容矫正',
    `customer_name` VARCHAR(100) NULL
        COMMENT 'WB userName 有, Ozon 接口不返 → NULL (前端显示"匿名买家")',
    `platform_sku_id` VARCHAR(64) NULL
        COMMENT 'WB nmId / Ozon sku',
    `platform_product_name` VARCHAR(500) NULL
        COMMENT 'WB productName 直接含, Ozon 要 sku JOIN platform_listings 反查',
    `product_id` BIGINT UNSIGNED NULL
        COMMENT '本地 products.id 反查关联 (可空, 兜底跨店匹配)',
    `created_at_platform` DATETIME NULL
        COMMENT '平台评价原始时间 (UTC naive, 跟项目规则 6)',
    `existing_reply_ru` TEXT NULL
        COMMENT '平台已有的回复 (拉取时填, 后续 sync 时刷新)',
    `existing_reply_at` DATETIME NULL,
    `is_answered` TINYINT(1) NOT NULL DEFAULT 0
        COMMENT '平台是否已标记已回复 (WB isAnswered / Ozon status=PROCESSED)',
    `status` ENUM('unread', 'read', 'replied', 'auto_replied', 'ignored') NOT NULL DEFAULT 'unread'
        COMMENT '本系统业务状态 (跟 is_answered 不等价: unread→read 是用户在 UI 看了)',
    `raw_payload` JSON NULL
        COMMENT '原始 API 响应 (debug + 字段扩展兜底)',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_review` (`tenant_id`, `shop_id`, `platform`, `platform_review_id`),
    INDEX `idx_shop_status_time` (`shop_id`, `status`, `created_at_platform`),
    INDEX `idx_tenant_shop_platform` (`tenant_id`, `shop_id`, `platform`),
    INDEX `idx_unread_per_shop` (`shop_id`, `is_answered`, `status`)
        COMMENT '红点角标: WHERE shop_id=? AND is_answered=0 AND status=unread'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='店铺买家评价主表 (WB Feedbacks + Ozon Review 统一存)';


-- ==================== 2. 回复历史 (含草稿 + 真实发送) ====================
CREATE TABLE IF NOT EXISTS `shop_review_replies` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `review_id` BIGINT UNSIGNED NOT NULL
        COMMENT 'shop_reviews.id 关联',
    -- AI 草稿
    `draft_content_ru` TEXT NULL
        COMMENT 'AI 生成的俄语草稿',
    `draft_content_zh` TEXT NULL
        COMMENT '草稿的中文翻译给老板看',
    `custom_hint` VARCHAR(500) NULL
        COMMENT '用户输入的重点 ("提一下 30 天无理由退换" 等)',
    `generated_count` SMALLINT UNSIGNED NOT NULL DEFAULT 0
        COMMENT '第几次重新生成 (0=首次)',
    `ai_model` VARCHAR(50) NULL
        COMMENT '生成草稿用的 AI 模型 ("deepseek-v3" 等)',
    -- 真实发送
    `final_content_ru` TEXT NULL
        COMMENT '真实发送的俄语 (用户编辑后或直接用草稿)',
    `final_content_zh` TEXT NULL
        COMMENT '最终发送内容的中文翻译',
    `sent_at` DATETIME NULL,
    `sent_status` ENUM('draft', 'pending', 'sent', 'failed') NOT NULL DEFAULT 'draft'
        COMMENT 'draft=未发, pending=排队, sent=已发, failed=平台拒收',
    `sent_error_msg` VARCHAR(500) NULL
        COMMENT '失败时平台真错原因 (透传给前端)',
    `is_auto` TINYINT(1) NOT NULL DEFAULT 0
        COMMENT '是否走自动回复路径 (4-5 星 + auto_reply_enabled=1)',
    `sent_by` BIGINT UNSIGNED NULL
        COMMENT 'user_id (auto 时 NULL)',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_review_time` (`review_id`, `created_at`),
    INDEX `idx_tenant_status` (`tenant_id`, `sent_status`),
    INDEX `idx_pending_send` (`sent_status`, `created_at`)
        COMMENT 'Celery 任务扫 pending 待发送'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='评价回复历史 (含草稿 + 真实发送), 一条评价多版本回复留痕';


-- ==================== 3. 店铺级配置 ====================
CREATE TABLE IF NOT EXISTS `shop_review_settings` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `shop_id` BIGINT UNSIGNED NOT NULL,
    `auto_reply_enabled` TINYINT(1) NOT NULL DEFAULT 0
        COMMENT '自动回复开关 (用户拍: 4-5 星才自动, 1-3 星仍人工)',
    `auto_reply_rating_floor` TINYINT UNSIGNED NOT NULL DEFAULT 4
        COMMENT '自动回复评分下限 (≥ 此星才自动回, 默认 4 即 4-5 星)',
    `reply_tone` ENUM('formal', 'friendly', 'warm') NOT NULL DEFAULT 'friendly'
        COMMENT '回复语气 — 默认 friendly (友好+温暖)',
    `brand_signature` VARCHAR(200) NULL
        COMMENT '结尾签名 ("С любовью, Sharino" 等), prompt 注入',
    `custom_prompt_extra` VARCHAR(1000) NULL
        COMMENT '用户自定义 prompt 补充 (品牌特殊调性等), 拼接到 prompt 末尾',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_shop` (`shop_id`),
    INDEX `idx_tenant` (`tenant_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='店铺级评价回复配置 (自动回复开关 + 语气 + 签名)';
