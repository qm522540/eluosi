-- Migration: 035_listings_category_extra_id.sql
-- Author: 老张
-- Date: 2026-04-17
-- Description:
--   platform_listings 加 platform_category_extra_id 字段
--   Ozon 分类需要 description_category_id + type_id 两个 ID，单个 platform_category_id 不够
--   同步时回填 type_id，避免广告/属性接口每次即时反查
--   WB 该字段永远为空
--
--   category_platform_mappings 里早已有同名字段（028 迁移加的），这里对齐到 listing 层

SET NAMES utf8mb4;

SET @has_col := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'platform_listings'
      AND COLUMN_NAME = 'platform_category_extra_id'
);
SET @sql := IF(@has_col = 0,
    "ALTER TABLE `platform_listings`
        ADD COLUMN `platform_category_extra_id` VARCHAR(100) DEFAULT NULL
        COMMENT 'Ozon=type_id, WB/Yandex 为空' AFTER `platform_category_name`",
    'SELECT 1');
PREPARE s1 FROM @sql; EXECUTE s1; DEALLOCATE PREPARE s1;
