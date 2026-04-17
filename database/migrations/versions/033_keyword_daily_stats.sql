-- Migration: 033_keyword_daily_stats.sql
-- Author: 老张
-- Date: 2026-04-17
-- Description:
--   关键词每日统计表，存储从 WB/Ozon 拉取的关键词效果数据
--   Celery 每日增量拉取 + 手动回填 90 天
--   数据保留 90 天，每日清理过期

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS `keyword_daily_stats` (
    `id`                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`             BIGINT UNSIGNED NOT NULL,
    `shop_id`               BIGINT UNSIGNED NOT NULL,
    `platform`              ENUM('wb', 'ozon') NOT NULL,
    `campaign_id`           BIGINT UNSIGNED DEFAULT NULL COMMENT '本地 ad_campaigns.id',
    `platform_campaign_id`  VARCHAR(100) DEFAULT NULL    COMMENT '平台活动ID（冗余，排查用）',
    `keyword`               VARCHAR(500) NOT NULL        COMMENT '关键词文本',
    `sku`                   VARCHAR(100) DEFAULT NULL    COMMENT '商品SKU（Ozon有，WB为空）',
    `stat_date`             DATE NOT NULL                COMMENT '统计日期',
    `impressions`           INT NOT NULL DEFAULT 0,
    `clicks`                INT NOT NULL DEFAULT 0,
    `spend`                 DECIMAL(12,2) NOT NULL DEFAULT 0 COMMENT '花费（卢布）',
    `ctr`                   DECIMAL(8,4) NOT NULL DEFAULT 0  COMMENT '点击率（%）',
    `cpc`                   DECIMAL(10,2) NOT NULL DEFAULT 0 COMMENT '单次点击成本（卢布）',
    `created_at`            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_kw_stat` (`tenant_id`, `shop_id`, `campaign_id`, `keyword`(200), `sku`(50), `stat_date`),
    INDEX `idx_shop_date` (`tenant_id`, `shop_id`, `stat_date`),
    INDEX `idx_keyword` (`tenant_id`, `shop_id`, `keyword`(100))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='关键词每日统计（WB/Ozon，90天保留）';
