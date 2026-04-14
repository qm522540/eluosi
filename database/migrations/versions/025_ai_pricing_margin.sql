-- Migration: 025_ai_pricing_margin.sql
-- Author: 老林（系统架构师）
-- Date: 2026-04-14
-- Description:
--   AI调价逻辑升级：从ROAS判断改为净毛利率+客单价驱动
--   1) products 新增 net_margin 字段（商品级别净毛利率）
--   2) ai_pricing_configs 新增 3 个字段：
--      - default_client_price  默认客单价
--      - auto_remove_losing_sku 是否自动删除亏损SKU
--      - losing_days_threshold  亏损观察天数
--   3) bid_adjustment_logs.execute_type 枚举新增 auto_remove

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- =====================================================================
-- Step 1: products 新增 net_margin 字段
-- 商品级别净毛利率，为空时使用 ai_pricing_configs.gross_margin 兜底
-- =====================================================================
ALTER TABLE `products`
    ADD COLUMN `net_margin` DECIMAL(5,2) DEFAULT NULL
        COMMENT '商品净毛利率(0-1)，为空则使用店铺默认配置gross_margin'
        AFTER `cost_price`;

-- =====================================================================
-- Step 2: ai_pricing_configs 新增 3 个字段
-- =====================================================================
ALTER TABLE `ai_pricing_configs`
    ADD COLUMN `default_client_price` DECIMAL(10,2) NOT NULL DEFAULT 600.00
        COMMENT '默认客单价（卢布），商品表无数据时使用'
        AFTER `aggressive_config`,
    ADD COLUMN `auto_remove_losing_sku` TINYINT(1) NOT NULL DEFAULT 0
        COMMENT '是否自动删除持续亏损SKU：0=不删除 1=自动删除'
        AFTER `default_client_price`,
    ADD COLUMN `losing_days_threshold` INT NOT NULL DEFAULT 21
        COMMENT '亏损判断观察天数，默认21天'
        AFTER `auto_remove_losing_sku`;

-- =====================================================================
-- Step 3: bid_adjustment_logs.execute_type 枚举新增 auto_remove
-- 原枚举：time_pricing / ai_auto / ai_manual / user_manual / time_restore
-- 新增：auto_remove（自动删除持续亏损SKU）
-- =====================================================================
ALTER TABLE `bid_adjustment_logs`
    MODIFY COLUMN `execute_type`
        ENUM('time_pricing','ai_auto','ai_manual','user_manual','time_restore','auto_remove')
        NOT NULL
        COMMENT 'time_pricing=分时调价/ai_auto=AI自动/ai_manual=AI建议人工确认/user_manual=用户手动/time_restore=分时恢复/auto_remove=自动删除亏损SKU';

SET FOREIGN_KEY_CHECKS = 1;
