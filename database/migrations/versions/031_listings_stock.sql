-- Migration: 031_listings_stock.sql
-- Author: 老张
-- Date: 2026-04-16
-- Description:
--   platform_listings 加 stock 字段，同步时从平台拉取显示库存
--   WB: /api/v1/supplier/stocks（按仓库，聚合 quantity）
--   OZON: info/list 的 stocks.stocks[].present（fbo/fbs 合计）
--   只用于显示，不允许编辑

SET NAMES utf8mb4;

SET @has_col := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'platform_listings'
      AND COLUMN_NAME = 'stock'
);
SET @add_col_sql := IF(@has_col = 0,
    "ALTER TABLE `platform_listings` ADD COLUMN `stock` INT NOT NULL DEFAULT 0 COMMENT '当前可售库存（平台同步，只读）' AFTER `price`",
    'SELECT 1');
PREPARE s1 FROM @add_col_sql; EXECUTE s1; DEALLOCATE PREPARE s1;

SET @has_ts := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'platform_listings'
      AND COLUMN_NAME = 'stock_updated_at'
);
SET @add_ts_sql := IF(@has_ts = 0,
    "ALTER TABLE `platform_listings` ADD COLUMN `stock_updated_at` DATETIME DEFAULT NULL COMMENT '库存最后同步时间' AFTER `stock`",
    'SELECT 1');
PREPARE s2 FROM @add_ts_sql; EXECUTE s2; DEALLOCATE PREPARE s2;
