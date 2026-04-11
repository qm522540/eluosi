-- Migration: 023_bid_management.sql
-- Author: 老林（系统架构师）
-- Date: 2026-04-11
-- Description:
--   出价管理模块数据库重构
--   1) DROP 并重建 ai_pricing_configs（改为店铺级单行 + 3模板JSON）
--   2) DROP 并重建 ai_pricing_suggestions（字段精简 + product_stage + 次日过期）
--   3) 新建 time_pricing_rules（店铺级分时调价规则）
--   4) 新建 bid_adjustment_logs（分时+AI合并的调价日志）
--   5) ad_groups 补 4 个字段（user_managed / original_bid / last_auto_bid / user_managed_at）
--   6) shop_data_init_status 补 data_days 字段
--   7) 清理 ad_campaigns 上的旧外键及残留列
--   8) 初始化 Ozon 店铺数据
--
-- 【破坏性变更警告】
--   本迁移会 DROP 旧版 ai_pricing_configs / ai_pricing_suggestions，
--   旧建议记录将永久丢失。执行前请由 DBA 手动备份：
--     CREATE TABLE _bak_ai_pricing_configs_20260411 AS SELECT * FROM ai_pricing_configs;
--     CREATE TABLE _bak_ai_pricing_suggestions_20260411 AS SELECT * FROM ai_pricing_suggestions;

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- =====================================================================
-- Step 1: 清理 ad_campaigns 上对旧 ai_pricing_configs 的外键与残留列
-- 老张注：生产环境实测没有 fk_campaign_pricing_config 外键，
--   原 DROP FOREIGN KEY 语句在生产会失败，改用 INFORMATION_SCHEMA 安全检查。
--   set FOREIGN_KEY_CHECKS=0 已在文件顶部，DROP COLUMN 不会触发 fk 检查。
-- =====================================================================

-- 安全 DROP FOREIGN KEY（仅在存在时执行）
SET @fk_exists = (
    SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
    WHERE CONSTRAINT_SCHEMA = DATABASE()
      AND TABLE_NAME = 'ad_campaigns'
      AND CONSTRAINT_NAME = 'fk_campaign_pricing_config'
);
SET @sql = IF(@fk_exists > 0,
    'ALTER TABLE ad_campaigns DROP FOREIGN KEY fk_campaign_pricing_config',
    'SELECT 1');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

ALTER TABLE `ad_campaigns`
    DROP COLUMN `pricing_config_id`,
    DROP COLUMN `custom_max_bid`,
    DROP COLUMN `custom_daily_budget`,
    DROP COLUMN `custom_target_roas`;

-- =====================================================================
-- Step 2: DROP 旧 AI 调价表
-- =====================================================================
DROP TABLE IF EXISTS `ai_pricing_suggestions`;
DROP TABLE IF EXISTS `ai_pricing_configs`;

-- =====================================================================
-- Step 3: ad_groups 补字段（用户手动管理标记 + 基准出价 + 系统末次出价）
-- =====================================================================
ALTER TABLE `ad_groups`
    ADD COLUMN `user_managed` TINYINT(1) NOT NULL DEFAULT 0
        COMMENT '用户手动管理，出价管理模块跳过该组' AFTER `status`,
    ADD COLUMN `user_managed_at` DATETIME DEFAULT NULL
        COMMENT '标记为用户管理的时间' AFTER `user_managed`,
    ADD COLUMN `original_bid` DECIMAL(10,2) DEFAULT NULL
        COMMENT '规则开启时记录的原始出价基准（用于分时调价按比例计算）' AFTER `user_managed_at`,
    ADD COLUMN `last_auto_bid` DECIMAL(10,2) DEFAULT NULL
        COMMENT '系统上次自动设置的出价（用于检测是否被用户手动改动）' AFTER `original_bid`;

-- =====================================================================
-- Step 4: shop_data_init_status 补 data_days 字段
-- =====================================================================
ALTER TABLE `shop_data_init_status`
    ADD COLUMN `data_days` INT UNSIGNED NOT NULL DEFAULT 0
        COMMENT '当前已积累的有效数据天数（用于AI冷启动判断）' AFTER `last_sync_at`;

-- =====================================================================
-- Step 5: 新建 time_pricing_rules（店铺级分时调价规则，单行）
-- =====================================================================
CREATE TABLE IF NOT EXISTS `time_pricing_rules` (
    `id`                  INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`           BIGINT UNSIGNED NOT NULL,
    `shop_id`             BIGINT UNSIGNED NOT NULL COMMENT '一个店铺只有一条规则',
    `peak_hours`          JSON NOT NULL COMMENT '高峰期小时列表（莫斯科时间0-23）',
    `peak_ratio`          SMALLINT UNSIGNED NOT NULL DEFAULT 120 COMMENT '高峰期出价系数%',
    `mid_hours`           JSON NOT NULL COMMENT '次高峰期小时列表',
    `mid_ratio`           SMALLINT UNSIGNED NOT NULL DEFAULT 100 COMMENT '次高峰期出价系数%',
    `low_hours`           JSON NOT NULL COMMENT '低谷期小时列表',
    `low_ratio`           SMALLINT UNSIGNED NOT NULL DEFAULT 60 COMMENT '低谷期出价系数%',
    `is_active`           TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否启用',
    `last_executed_at`    DATETIME DEFAULT NULL COMMENT '上次执行时间',
    `last_execute_result` VARCHAR(200) DEFAULT NULL COMMENT '上次执行结果摘要',
    `created_at`          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_time_pricing_shop` (`shop_id`),
    INDEX `idx_time_pricing_tenant` (`tenant_id`),
    CONSTRAINT `fk_time_pricing_tenant` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_time_pricing_shop`   FOREIGN KEY (`shop_id`)   REFERENCES `shops` (`id`)   ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='店铺级分时调价规则';

-- =====================================================================
-- Step 6: 新建 ai_pricing_configs（店铺级单行，3个模板 + 失败重试）
-- =====================================================================
CREATE TABLE IF NOT EXISTS `ai_pricing_configs` (
    `id`                  INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`           BIGINT UNSIGNED NOT NULL,
    `shop_id`             BIGINT UNSIGNED NOT NULL COMMENT '一个店铺只有一条配置',
    `is_active`           TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否启用AI调价',
    `auto_execute`        TINYINT(1) NOT NULL DEFAULT 0 COMMENT '0=建议模式 1=自动执行',
    `template_name`       ENUM('conservative','default','aggressive') NOT NULL DEFAULT 'default'
                          COMMENT '当前选中的模板',
    `conservative_config` JSON NOT NULL COMMENT '保守模板参数',
    `default_config`      JSON NOT NULL COMMENT '默认模板参数',
    `aggressive_config`   JSON NOT NULL COMMENT '激进模板参数',
    `last_executed_at`    DATETIME DEFAULT NULL,
    `last_execute_status` ENUM('success','failed','partial') DEFAULT NULL,
    `last_error_msg`      TEXT DEFAULT NULL COMMENT '上次失败原因',
    `retry_at`            DATETIME DEFAULT NULL COMMENT '失败后30分钟重试时间点',
    `created_at`          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_ai_pricing_shop` (`shop_id`),
    INDEX `idx_ai_pricing_tenant` (`tenant_id`),
    CONSTRAINT `fk_ai_pricing_tenant` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_ai_pricing_shop`   FOREIGN KEY (`shop_id`)   REFERENCES `shops` (`id`)   ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='店铺级AI调价配置（单行+三模板）';

-- =====================================================================
-- Step 7: 新建 ai_pricing_suggestions（精简版 + product_stage + 次日过期）
-- =====================================================================
CREATE TABLE IF NOT EXISTS `ai_pricing_suggestions` (
    `id`               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`        BIGINT UNSIGNED NOT NULL,
    `shop_id`          BIGINT UNSIGNED NOT NULL,
    `campaign_id`      BIGINT UNSIGNED NOT NULL,
    `platform_sku_id`  VARCHAR(100) NOT NULL COMMENT 'Ozon数字SKU',
    `sku_name`         VARCHAR(300) DEFAULT NULL,
    `current_bid`      DECIMAL(10,2) NOT NULL COMMENT '当前出价（卢布）',
    `suggested_bid`    DECIMAL(10,2) NOT NULL COMMENT 'AI建议出价（卢布）',
    `adjust_pct`       DECIMAL(5,2) NOT NULL COMMENT '调整幅度%（正加负降）',
    `product_stage`    ENUM('cold_start','testing','growing','declining','unknown') NOT NULL DEFAULT 'unknown'
                       COMMENT '商品阶段',
    `decision_basis`   ENUM('history_data','shop_benchmark','cold_start_baseline','imported_data') NOT NULL DEFAULT 'shop_benchmark'
                       COMMENT '决策依据',
    `current_roas`     DECIMAL(5,2) DEFAULT NULL,
    `expected_roas`    DECIMAL(5,2) DEFAULT NULL,
    `data_days`        INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '历史数据天数',
    `reason`           TEXT DEFAULT NULL COMMENT 'AI调整理由',
    `status`           ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending',
    `generated_at`     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '生成时间（次日过期）',
    `executed_at`      DATETIME DEFAULT NULL,
    PRIMARY KEY (`id`),
    INDEX `idx_suggest_tenant`    (`tenant_id`),
    INDEX `idx_suggest_shop_stat` (`shop_id`, `status`),
    INDEX `idx_suggest_campaign`  (`campaign_id`),
    INDEX `idx_suggest_generated` (`generated_at`),
    CONSTRAINT `fk_suggest_tenant`   FOREIGN KEY (`tenant_id`)   REFERENCES `tenants` (`id`)      ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_suggest_shop`     FOREIGN KEY (`shop_id`)     REFERENCES `shops` (`id`)        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_suggest_campaign` FOREIGN KEY (`campaign_id`) REFERENCES `ad_campaigns` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AI调价建议';

-- =====================================================================
-- Step 8: 新建 bid_adjustment_logs（分时+AI合并的出价调整日志）
-- =====================================================================
CREATE TABLE IF NOT EXISTS `bid_adjustment_logs` (
    `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`       BIGINT UNSIGNED NOT NULL,
    `shop_id`         BIGINT UNSIGNED NOT NULL,
    `campaign_id`     BIGINT UNSIGNED NOT NULL,
    `campaign_name`   VARCHAR(200) DEFAULT NULL COMMENT '活动名称快照',
    `platform_sku_id` VARCHAR(100) NOT NULL,
    `sku_name`        VARCHAR(300) DEFAULT NULL,
    `old_bid`         DECIMAL(10,2) NOT NULL,
    `new_bid`         DECIMAL(10,2) NOT NULL,
    `adjust_pct`      DECIMAL(5,2) NOT NULL,
    `execute_type`    ENUM('time_pricing','ai_auto','ai_manual','user_manual') NOT NULL
                      COMMENT 'time_pricing=分时调价/ai_auto=AI自动/ai_manual=AI建议人工确认/user_manual=用户手动',
    `time_period`     ENUM('peak','mid','low') DEFAULT NULL COMMENT '分时调价专用',
    `period_ratio`    SMALLINT UNSIGNED DEFAULT NULL COMMENT '分时调价专用',
    `product_stage`   VARCHAR(20) DEFAULT NULL COMMENT 'AI调价专用',
    `moscow_hour`     TINYINT UNSIGNED DEFAULT NULL COMMENT '执行时莫斯科小时 0-23',
    `success`         TINYINT(1) NOT NULL DEFAULT 1,
    `error_msg`       VARCHAR(500) DEFAULT NULL,
    `created_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_bidlog_tenant`       (`tenant_id`),
    INDEX `idx_bidlog_shop_created` (`shop_id`, `created_at`),
    INDEX `idx_bidlog_campaign`     (`campaign_id`),
    INDEX `idx_bidlog_exec_type`    (`execute_type`),
    CONSTRAINT `fk_bidlog_tenant`   FOREIGN KEY (`tenant_id`)   REFERENCES `tenants` (`id`)      ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_bidlog_shop`     FOREIGN KEY (`shop_id`)     REFERENCES `shops` (`id`)        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_bidlog_campaign` FOREIGN KEY (`campaign_id`) REFERENCES `ad_campaigns` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='出价调整日志（分时+AI合并）';

SET FOREIGN_KEY_CHECKS = 1;

-- =====================================================================
-- Step 9: 初始化现有 Ozon 店铺数据
--   - time_pricing_rules: 默认高峰/次高峰/低谷三段
--   - ai_pricing_configs: 默认三模板JSON
--   - shop_data_init_status: 021 已初始化，这里跳过
-- =====================================================================

-- 9.1 time_pricing_rules 默认行
INSERT IGNORE INTO `time_pricing_rules`
    (`tenant_id`, `shop_id`, `peak_hours`, `peak_ratio`, `mid_hours`, `mid_ratio`, `low_hours`, `low_ratio`, `is_active`)
SELECT
    `tenant_id`,
    `id`,
    CAST('[10,11,12,13,19,20,21,22]' AS JSON),
    120,
    CAST('[7,8,9,14,15,16,17,18]'    AS JSON),
    100,
    CAST('[0,1,2,3,4,5,6,23]'        AS JSON),
    60,
    0
FROM `shops`
WHERE `platform` = 'ozon';

-- 9.2 ai_pricing_configs 默认行（三个模板预设）
INSERT IGNORE INTO `ai_pricing_configs`
    (`tenant_id`, `shop_id`, `is_active`, `auto_execute`, `template_name`,
     `conservative_config`, `default_config`, `aggressive_config`)
SELECT
    `tenant_id`,
    `id`,
    0,
    0,
    'default',
    CAST('{"target_roas":2.0,"min_roas":1.5,"max_bid":100,"daily_budget":500,"max_adjust_pct":15,"gross_margin":0.5}' AS JSON),
    CAST('{"target_roas":3.0,"min_roas":1.8,"max_bid":180,"daily_budget":2000,"max_adjust_pct":30,"gross_margin":0.5}' AS JSON),
    CAST('{"target_roas":4.0,"min_roas":2.5,"max_bid":300,"daily_budget":0,"max_adjust_pct":25,"gross_margin":0.5}' AS JSON)
FROM `shops`
WHERE `platform` = 'ozon';
