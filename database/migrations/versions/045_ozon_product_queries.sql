-- Migration: 045_ozon_product_queries.sql
-- Author: 老林
-- Date: 2026-04-18
-- Description:
--   Ozon SKU × 搜索词维度数据本地存储
--   数据源：POST /v1/analytics/product-queries/details (Premium 接口)
--   Celery 每日凌晨同步，前端商品出价展开 SKU 时直接查本地表秒出
--   保留 90 天

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS `ozon_product_queries` (
    `id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`      BIGINT UNSIGNED NOT NULL,
    `shop_id`        BIGINT UNSIGNED NOT NULL,
    `sku`            VARCHAR(50) NOT NULL          COMMENT 'Ozon SKU',
    `query`          VARCHAR(500) NOT NULL         COMMENT '用户搜索词',
    `stat_date`      DATE NOT NULL                 COMMENT '统计日期（拉取日，因 API 返回区间总和而非按天）',
    `impressions`    INT NOT NULL DEFAULT 0,
    `clicks`         INT NOT NULL DEFAULT 0,
    `add_to_cart`    INT NOT NULL DEFAULT 0,
    `orders`         INT NOT NULL DEFAULT 0,
    `revenue`        DECIMAL(12,2) NOT NULL DEFAULT 0,
    `frequency`      INT NOT NULL DEFAULT 0        COMMENT '搜索频次（Ozon 内部频次指标）',
    `view_conversion` DECIMAL(8,4) NOT NULL DEFAULT 0 COMMENT '曝光→点击转化率',
    `date_from`      DATE NOT NULL                 COMMENT '本次统计的起始日',
    `date_to`        DATE NOT NULL                 COMMENT '本次统计的结束日',
    `created_at`     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_sku_query_date` (`tenant_id`, `shop_id`, `sku`, `query`(200), `stat_date`),
    INDEX `idx_shop_sku` (`tenant_id`, `shop_id`, `sku`),
    INDEX `idx_tenant_date` (`tenant_id`, `stat_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Ozon SKU × 搜索词维度统计（来自 product-queries/details，需 Premium 订阅）';
