-- Migration: 039_drop_legacy_category.sql
-- Author: 老张
-- Date: 2026-04-17
-- Description:
--   清理两个历史遗留：
--   1) products.category 字符串字段（已被 local_category_id 完全取代）
--   2) 旧表 category_mappings（026 创建，028 新建 category_platform_mappings
--      后实际未再被写入，当前生产数据 0 行）
--
--   前置检查：生产确认 category_mappings 0 行、products.category 无业务依赖
--   （只在 _product_to_dict 里返回，前端不消费 —— 前端只用 local_category_name）

SET NAMES utf8mb4;

-- Step 1: drop 旧 category_mappings 表（026 遗留，已被 category_platform_mappings 取代）
DROP TABLE IF EXISTS `category_mappings`;

-- Step 2: drop products.category 列（已被 local_category_id 取代）
SET @has_col := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'products'
      AND COLUMN_NAME = 'category'
);
SET @sql := IF(@has_col > 0,
    "ALTER TABLE `products` DROP COLUMN `category`",
    'SELECT 1');
PREPARE s1 FROM @sql; EXECUTE s1; DEALLOCATE PREPARE s1;
