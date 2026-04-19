-- Migration: 048_seo_keyword_candidates.sql
-- Author: 老张
-- Date: 2026-04-19
-- Description:
--   SEO 优化候选词池（付费词反哺自然词 + 多源融合 SEO 建议）
--   数据来源多个源（A 付费 / B 自然 / C 类目 / D Wordstat），一条词哪怕只
--   命中 1 个源也先入库，后续追加源直接 UPDATE sources JSON，不改表结构。
--
--   一期仅接入源 A（付费词，ad_keywords + ad_stats）+ C1-a（本店同类目付费聚合）。
--   二期接源 B（自然词，product_search_queries），三期接 Wordstat。
--
--   引擎（app/services/seo/service.py analyze_paid_to_organic）每次 refresh
--   全量重算该店的候选池并 upsert（status 字段保留用户已处理状态）。
--
--   注意：一期/二期仅读写本表，不动 products.title；三期接入 AI 标题
--   生成时再加写商品接口（权限一并定）。

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS `seo_keyword_candidates` (
    `id`                      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`               BIGINT UNSIGNED NOT NULL,
    `shop_id`                 BIGINT UNSIGNED NOT NULL,
    `product_id`              BIGINT UNSIGNED NOT NULL,
    `keyword`                 VARCHAR(200) NOT NULL        COMMENT '候选关键词（俄语，已 lower）',
    `sources`                 JSON NOT NULL                COMMENT '数据来源数组，元素 {type, scope}，见文档',
    `score`                   DECIMAL(6,2) NOT NULL DEFAULT 0 COMMENT '综合得分，多源叠加 + 指标加权',

    -- 源 A 付费指标
    `paid_roas`               DECIMAL(8,2) DEFAULT NULL    COMMENT '付费 ROAS',
    `paid_orders`             INT DEFAULT NULL             COMMENT '付费订单数',
    `paid_spend`              DECIMAL(12,2) DEFAULT NULL   COMMENT '付费花费',
    `paid_revenue`            DECIMAL(12,2) DEFAULT NULL   COMMENT '付费营收',

    -- 源 B 自然指标（二期填）
    `organic_impressions`     INT DEFAULT NULL             COMMENT '自然曝光',
    `organic_add_to_cart`     INT DEFAULT NULL             COMMENT '自然加购',
    `organic_orders`          INT DEFAULT NULL             COMMENT '自然订单',

    -- 源 D Wordstat（五期填）
    `wordstat_volume`         INT DEFAULT NULL             COMMENT 'Wordstat 月搜索量',

    -- 覆盖情况
    `in_title`                TINYINT(1) NOT NULL DEFAULT 0 COMMENT '当前标题是否已覆盖（lower 包含）',
    `in_attrs`                TINYINT(1) NOT NULL DEFAULT 0 COMMENT '商品属性拼接文本是否覆盖',

    -- 用户处理状态
    `status`                  ENUM('pending', 'adopted', 'ignored', 'processed') NOT NULL DEFAULT 'pending'
                                                           COMMENT 'pending 待处理 / adopted 已加入候选 / ignored 忽略 / processed 已应用到商品',
    `adopted_at`              DATETIME DEFAULT NULL        COMMENT '用户点"加入标题"时间',
    `adopted_by`              BIGINT UNSIGNED DEFAULT NULL COMMENT '用户 ID',

    `created_at`              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                                       ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_skc` (`tenant_id`, `shop_id`, `product_id`, `keyword`(100)),
    INDEX `idx_shop_status` (`tenant_id`, `shop_id`, `status`),
    INDEX `idx_shop_score` (`tenant_id`, `shop_id`, `score`),
    INDEX `idx_product` (`tenant_id`, `product_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='SEO 优化候选词池（多源融合，付费反哺自然）';
