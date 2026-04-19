-- Migration: 048_shops_yandex_business_campaign.sql
-- Author: 老林
-- Date: 2026-04-19
-- Description:
--   shops 表加 Yandex 专用字段：business_id + campaign_id
--   YandexClient.fetch_products 强依赖这俩，之前 shops 没存导致无法拉商品。
--   wb/ozon 留空。

SET NAMES utf8mb4;

ALTER TABLE `shops`
    ADD COLUMN `yandex_business_id` VARCHAR(100) DEFAULT NULL
        COMMENT 'Yandex Market business ID（仅 yandex 平台用）',
    ADD COLUMN `yandex_campaign_id` VARCHAR(100) DEFAULT NULL
        COMMENT 'Yandex Market campaign ID（仅 yandex 平台用）';
