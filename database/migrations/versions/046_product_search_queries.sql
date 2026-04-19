-- Migration: 043_product_search_queries.sql
-- Author: 老张
-- Date: 2026-04-18
-- Description:
--   搜索词洞察（SEO流量分析）底表：商品被搜索词每日统计
--   数据源：
--     WB  POST /api/v2/search-report/product/search-texts（需 Jam 订阅）
--     Ozon POST /v1/analytics/product-queries/details   （需 Premium 订阅）
--   字段按两平台并集；平台特有字段放 extra JSON
--   数据保留 90 天，每日清理过期

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS `product_search_queries` (
    `id`                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`         BIGINT UNSIGNED NOT NULL,
    `shop_id`           BIGINT UNSIGNED NOT NULL,
    `platform`          ENUM('wb', 'ozon') NOT NULL,
    `platform_sku_id`   VARCHAR(100) NOT NULL        COMMENT 'WB nmId / Ozon sku',
    `product_id`        BIGINT UNSIGNED DEFAULT NULL COMMENT '本地 products.id（反查时填）',
    `query_text`        VARCHAR(500) NOT NULL        COMMENT '用户搜索词',
    `stat_date`         DATE NOT NULL                COMMENT '统计日期（period 结束日）',
    `frequency`         INT NOT NULL DEFAULT 0       COMMENT 'WB frequency / Ozon unique_search_users',
    `impressions`       INT NOT NULL DEFAULT 0       COMMENT 'WB openCard 卡片浏览 / Ozon view_count',
    `clicks`            INT NOT NULL DEFAULT 0       COMMENT '点击（部分平台无）',
    `add_to_cart`       INT NOT NULL DEFAULT 0       COMMENT '加购',
    `orders`            INT NOT NULL DEFAULT 0       COMMENT '订单数',
    `revenue`           DECIMAL(12,2) NOT NULL DEFAULT 0 COMMENT '销售额（Ozon gmv / WB 推算）',
    `median_position`   DECIMAL(8,2) DEFAULT NULL    COMMENT '中位搜索位置（WB / Ozon Premium Plus）',
    `cart_to_order`     DECIMAL(8,4) DEFAULT NULL    COMMENT '购→订转化率（WB）',
    `view_conversion`   DECIMAL(8,4) DEFAULT NULL    COMMENT '浏览→购买转化（Ozon Premium Plus）',
    `extra`             JSON DEFAULT NULL            COMMENT '平台特有字段：dynamics/percentile 等',
    `created_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_psq` (`tenant_id`, `shop_id`, `platform_sku_id`, `query_text`(200), `stat_date`),
    INDEX `idx_shop_date` (`tenant_id`, `shop_id`, `stat_date`),
    INDEX `idx_product` (`tenant_id`, `product_id`),
    INDEX `idx_query` (`tenant_id`, `shop_id`, `query_text`(100))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='商品被搜索词统计（SEO流量洞察，需Jam/Premium订阅）';
