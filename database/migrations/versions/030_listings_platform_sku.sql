-- Migration: 030_listings_platform_sku.sql
-- Author: 老张
-- Date: 2026-04-16
-- Description:
--   platform_listings 加 platform_sku_id 字段
--   背景：OZON Performance API (/campaign/{id}/v2/products) 返回的 sku
--   是 OZON 的 SKU ID（和 info/list 响应里的 sku 字段一致），
--   和 platform_product_id 存的 product_id 不是同一个值。
--   加此字段让 "sku → listing" 的反查能在两个平台都工作。
--
--   - WB: platform_product_id == platform_sku_id == nm_id（冗余方便）
--   - Ozon: platform_product_id = product_id, platform_sku_id = sku

SET NAMES utf8mb4;

SET @has_col := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'platform_listings'
      AND COLUMN_NAME = 'platform_sku_id'
);
SET @add_col_sql := IF(@has_col = 0,
    "ALTER TABLE `platform_listings` ADD COLUMN `platform_sku_id` VARCHAR(100) DEFAULT NULL COMMENT 'OZON的sku_id / WB的nm_id（广告API返回的sku映射字段）' AFTER `platform_product_id`",
    'SELECT 1');
PREPARE s1 FROM @add_col_sql; EXECUTE s1; DEALLOCATE PREPARE s1;

-- 索引（按 shop+platform+sku 查）
SET @has_idx := (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'platform_listings'
      AND INDEX_NAME = 'idx_listings_sku'
);
SET @add_idx_sql := IF(@has_idx = 0,
    'ALTER TABLE `platform_listings` ADD INDEX `idx_listings_sku` (`tenant_id`, `shop_id`, `platform`, `platform_sku_id`)',
    'SELECT 1');
PREPARE s2 FROM @add_idx_sql; EXECUTE s2; DEALLOCATE PREPARE s2;

-- WB 直接回填 platform_sku_id = platform_product_id（nm_id 一致）
UPDATE `platform_listings`
SET `platform_sku_id` = `platform_product_id`
WHERE `platform` = 'wb'
  AND `platform_sku_id` IS NULL
  AND `platform_product_id` IS NOT NULL;

-- OZON 暂无法回填（要等下次同步从 info/list 的 sku 字段写入）
