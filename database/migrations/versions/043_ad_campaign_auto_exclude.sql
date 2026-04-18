-- Migration: 043_ad_campaign_auto_exclude.sql
-- Author: 老林
-- Date: 2026-04-18
-- Description:
--   广告活动级"自动屏蔽"托管功能
--   表 1：活动级开关配置（一个活动一行）
--   表 2：每次自动屏蔽产生的日志（每个被屏蔽词一条，含估算节省金额）

SET NAMES utf8mb4;

-- 表 1：活动级开关
CREATE TABLE IF NOT EXISTS `ad_campaign_auto_exclude` (
    `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`     BIGINT UNSIGNED NOT NULL,
    `shop_id`       BIGINT UNSIGNED NOT NULL,
    `campaign_id`   BIGINT UNSIGNED NOT NULL    COMMENT '本地 ad_campaigns.id',
    `enabled`       TINYINT(1) NOT NULL DEFAULT 0,
    `last_run_at`   DATETIME DEFAULT NULL       COMMENT '最近一次运行时间',
    `last_run_excluded` INT NOT NULL DEFAULT 0  COMMENT '最近一次屏蔽词数（快照）',
    `last_run_saved`    DECIMAL(12,2) NOT NULL DEFAULT 0 COMMENT '最近一次估算节省（卢布/月，快照）',
    `created_at`    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_camp` (`tenant_id`, `shop_id`, `campaign_id`),
    INDEX `idx_enabled` (`enabled`, `last_run_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='广告活动级自动屏蔽开关 + 最近运行快照';

-- 表 2：屏蔽日志（每个被屏蔽词一条）
CREATE TABLE IF NOT EXISTS `ad_auto_exclude_log` (
    `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`     BIGINT UNSIGNED NOT NULL,
    `shop_id`       BIGINT UNSIGNED NOT NULL,
    `campaign_id`   BIGINT UNSIGNED NOT NULL,
    `nm_id`         BIGINT UNSIGNED NOT NULL    COMMENT 'WB nm_id',
    `keyword`       VARCHAR(500) NOT NULL,
    `run_id`        VARCHAR(50) NOT NULL        COMMENT '同一次运行的批 ID（uuid）',
    `excluded_at`   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `saved_per_day` DECIMAL(12,4) NOT NULL DEFAULT 0 COMMENT '该词被屏蔽前 7 天日均花费（节省估算依据，卢布）',
    `reason`        VARCHAR(200) DEFAULT NULL   COMMENT '触发的规则简述（如 "CTR 0.3<1.0 且 花费 ¥120>平均"）',
    PRIMARY KEY (`id`),
    INDEX `idx_camp_time` (`tenant_id`, `campaign_id`, `excluded_at`),
    INDEX `idx_tenant_time` (`tenant_id`, `excluded_at`),
    INDEX `idx_run` (`run_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='活动自动屏蔽日志（每个被屏蔽词一条，含节省金额估算）';
