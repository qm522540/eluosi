-- Migration: 049_shops_yandex_business_campaign.sql
-- Author: 老林
-- Date: 2026-04-19（重号 2026-04-19，原 048，与老张 seo_keyword_candidates 撞号）
-- Description:
--   shops 表加 Yandex 专用字段：business_id + campaign_id
--   YandexClient.fetch_products 强依赖这俩，之前 shops 没存导致无法拉商品。
--   wb/ozon 留空。
--
--   重号说明：今日老张 11:15 推 048_seo_keyword_candidates，我下午没看
--   git log 又占了 048。生产已两边都跑（DESC shops 已确认有 yandex_*
--   字段，SHOW TABLES 已确认有 seo_keyword_candidates），仓库重命名仅
--   修复历史记录，不需要在生产重跑。

SET NAMES utf8mb4;

ALTER TABLE `shops`
    ADD COLUMN `yandex_business_id` VARCHAR(100) DEFAULT NULL
        COMMENT 'Yandex Market business ID（仅 yandex 平台用）',
    ADD COLUMN `yandex_campaign_id` VARCHAR(100) DEFAULT NULL
        COMMENT 'Yandex Market campaign ID（仅 yandex 平台用）';
