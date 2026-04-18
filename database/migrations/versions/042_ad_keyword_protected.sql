-- Migration: 042_ad_keyword_protected.sql
-- Author: 老林
-- Date: 2026-04-18
-- Description:
--   关键词智能屏蔽"白名单"（粒度 A：tenant + shop + campaign + nm_id + keyword）
--   勾入此表的 (campaign_id, nm_id, keyword) 即使被效能规则判为 waste，
--   也不会出现在"建议屏蔽"列表 + "一键屏蔽"会自动剔除。

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS `ad_keyword_protected` (
    `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`     BIGINT UNSIGNED NOT NULL,
    `shop_id`       BIGINT UNSIGNED NOT NULL,
    `campaign_id`   BIGINT UNSIGNED NOT NULL    COMMENT '本地 ad_campaigns.id',
    `nm_id`         BIGINT UNSIGNED NOT NULL    COMMENT 'WB nm_id（商品平台ID）',
    `keyword`       VARCHAR(500) NOT NULL       COMMENT '关键词文本（与 WB 屏蔽词一致大小写策略）',
    `created_at`    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_kw_protected` (`tenant_id`, `shop_id`, `campaign_id`, `nm_id`, `keyword`(200)),
    INDEX `idx_camp_nm` (`tenant_id`, `campaign_id`, `nm_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='关键词智能屏蔽白名单（粒度: tenant+shop+campaign+nm_id+keyword）';
