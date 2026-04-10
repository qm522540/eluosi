-- Migration: 016_ai_pricing.sql
-- Author: 老林
-- Date: 2026-04-10
-- Description: Create ai_pricing_configs and ai_pricing_suggestions tables for AI smart pricing module

SET NAMES utf8mb4;

-- -----------------------------------------------------------
-- Table: ai_pricing_configs (品类调价配置)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `ai_pricing_configs` (
    `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `shop_id` BIGINT UNSIGNED NOT NULL,
    `category_name` VARCHAR(100) NOT NULL COMMENT '品类名称，如饰品/电子数码',
    `target_roas` DECIMAL(5,2) NOT NULL DEFAULT 2.00 COMMENT '目标ROAS',
    `min_roas` DECIMAL(5,2) NOT NULL DEFAULT 1.20 COMMENT '最低可接受ROAS，低于此值降价',
    `gross_margin` DECIMAL(5,2) NOT NULL DEFAULT 0.50 COMMENT '毛利率，0-1之间',
    `daily_budget_limit` DECIMAL(10,2) NOT NULL DEFAULT 1000.00 COMMENT '日预算上限（卢布）',
    `max_bid` DECIMAL(10,2) NOT NULL DEFAULT 200.00 COMMENT '单次出价上限',
    `min_bid` DECIMAL(10,2) NOT NULL DEFAULT 3.00 COMMENT '最低出价（Ozon限制3卢布）',
    `max_adjust_pct` DECIMAL(5,2) NOT NULL DEFAULT 30.00 COMMENT '单次最大调幅%',
    `auto_execute` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否自动执行，0=建议模式 1=自动模式',
    `is_active` TINYINT(1) NOT NULL DEFAULT 1,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_pricing_config_shop_category` (`shop_id`, `category_name`),
    INDEX `idx_pricing_config_tenant` (`tenant_id`),
    CONSTRAINT `fk_pricing_config_tenant` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_pricing_config_shop` FOREIGN KEY (`shop_id`) REFERENCES `shops` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AI品类调价配置';

-- -----------------------------------------------------------
-- Table: ai_pricing_suggestions (AI调价建议记录)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `ai_pricing_suggestions` (
    `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `shop_id` BIGINT UNSIGNED NOT NULL,
    `campaign_id` BIGINT UNSIGNED NOT NULL COMMENT '关联ad_campaigns',
    `product_id` VARCHAR(100) DEFAULT NULL COMMENT '平台商品ID',
    `product_name` VARCHAR(200) DEFAULT NULL,
    `current_bid` DECIMAL(10,2) NOT NULL COMMENT '当前出价',
    `suggested_bid` DECIMAL(10,2) NOT NULL COMMENT 'AI建议出价',
    `adjust_pct` DECIMAL(5,2) NOT NULL COMMENT '调整幅度%，正为加价负为降价',
    `reason` TEXT DEFAULT NULL COMMENT 'AI给出的调整理由',
    `current_roas` DECIMAL(5,2) DEFAULT NULL COMMENT '当前ROAS',
    `expected_roas` DECIMAL(5,2) DEFAULT NULL COMMENT '预期ROAS',
    `current_spend` DECIMAL(10,2) DEFAULT NULL COMMENT '今日已花费',
    `daily_budget` DECIMAL(10,2) DEFAULT NULL COMMENT '日预算',
    `ai_model` VARCHAR(50) NOT NULL DEFAULT 'deepseek',
    `status` ENUM('pending','approved','rejected','executed','expired') NOT NULL DEFAULT 'pending',
    `auto_executed` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否自动执行',
    `executed_at` DATETIME DEFAULT NULL COMMENT '实际执行时间',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `expires_at` DATETIME DEFAULT NULL COMMENT '建议过期时间，默认2小时后',
    PRIMARY KEY (`id`),
    INDEX `idx_suggestion_tenant` (`tenant_id`),
    INDEX `idx_suggestion_shop` (`shop_id`),
    INDEX `idx_suggestion_campaign` (`campaign_id`),
    INDEX `idx_suggestion_status` (`status`),
    INDEX `idx_suggestion_created` (`created_at`),
    CONSTRAINT `fk_suggestion_tenant` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_suggestion_shop` FOREIGN KEY (`shop_id`) REFERENCES `shops` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_suggestion_campaign` FOREIGN KEY (`campaign_id`) REFERENCES `ad_campaigns` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AI调价建议记录';

-- -----------------------------------------------------------
-- Default preset data for ai_pricing_configs
-- Note: tenant_id=1, shop_id=1 as placeholder, adjust per actual deployment
-- -----------------------------------------------------------
INSERT INTO `ai_pricing_configs` (`tenant_id`, `shop_id`, `category_name`, `target_roas`, `min_roas`, `gross_margin`, `max_bid`, `min_bid`, `daily_budget_limit`, `max_adjust_pct`)
VALUES
    (1, 1, '饰品',     2.50, 1.50, 0.60, 150.00, 3.00, 2000.00, 30.00),
    (1, 1, '电子数码', 1.80, 1.20, 0.30, 200.00, 3.00, 3000.00, 30.00),
    (1, 1, '通用默认', 2.00, 1.20, 0.45, 180.00, 3.00, 1500.00, 30.00);
