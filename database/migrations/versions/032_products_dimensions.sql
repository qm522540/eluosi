-- Migration: 032_products_dimensions.sql
-- Author: 老张
-- Date: 2026-04-16
-- Description:
--   products 加长宽高字段（单位 mm）
--   WB: dimensions.{length,width,height} 单位 cm × 10
--   OZON: info 不返回，手动填或后续扩展

SET NAMES utf8mb4;

SET @has_len := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'products'
      AND COLUMN_NAME = 'length_mm'
);
SET @sql := IF(@has_len = 0,
    "ALTER TABLE `products`
        ADD COLUMN `length_mm` INT DEFAULT NULL COMMENT '长（毫米）' AFTER `weight_g`,
        ADD COLUMN `width_mm`  INT DEFAULT NULL COMMENT '宽（毫米）' AFTER `length_mm`,
        ADD COLUMN `height_mm` INT DEFAULT NULL COMMENT '高（毫米）' AFTER `width_mm`",
    'SELECT 1');
PREPARE s1 FROM @sql; EXECUTE s1; DEALLOCATE PREPARE s1;
