-- Migration: 040_product_listing_archived_status.sql
-- Author: 老张
-- Date: 2026-04-18
-- Description:
--   products.status 和 platform_listings.status 枚举加 'archived' 值。
--   语义：
--     - active    当前在架（平台 list 返回、可售）
--     - inactive  预留（用户主动停售）
--     - archived  平台 list 不再返回但历史有销售/listing 痕迹（供 region-detail
--                 等老订单反查 name_zh，不参与在架列表）
--     - deleted   用户主动删除（软删除）
--
--   解决 §21.4.3：Ozon region-detail 里 ~40% 老订单 SKU 查不到 name_zh
--   （如 QQ-B0031 / QQ-B0024 / QQ-B0043 / QQ-B0065），因为这些 SKU 在平台
--   已被完全移除，visibility=ALL 也拉不到，而同步逻辑未保留"本次未见但
--   之前见过"的记录。本次迁移先给字段类型留出 archived 值，代码侧后续
--   在 _sync_wb_products / _sync_ozon_products 结尾把本次未返回的 listing
--   标为 archived，不再误当作 deleted。

SET NAMES utf8mb4;

-- products.status
ALTER TABLE `products`
    MODIFY COLUMN `status` ENUM('active','inactive','deleted','archived')
    NOT NULL DEFAULT 'active';

-- platform_listings.status
ALTER TABLE `platform_listings`
    MODIFY COLUMN `status` ENUM('active','inactive','deleted','out_of_stock','blocked','archived')
    NOT NULL DEFAULT 'active';
