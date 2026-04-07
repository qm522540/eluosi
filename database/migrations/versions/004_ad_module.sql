-- Migration: 004_ad_module.sql
-- Author: 老林
-- Date: 2026-04-07
-- Description: Create ad_campaigns, ad_groups, ad_keywords, ad_stats tables

SET NAMES utf8mb4;

-- -----------------------------------------------------------
-- Table: ad_campaigns
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `ad_campaigns` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `shop_id` BIGINT UNSIGNED NOT NULL,
    `platform` ENUM('wb','ozon','yandex') NOT NULL,
    `platform_campaign_id` VARCHAR(100) NOT NULL,
    `name` VARCHAR(200) NOT NULL,
    `ad_type` ENUM('search','catalog','product_page','recommendation') NOT NULL,
    `daily_budget` DECIMAL(10,2) NULL DEFAULT NULL,
    `total_budget` DECIMAL(10,2) NULL DEFAULT NULL,
    `status` ENUM('active','paused','archived','draft') NOT NULL DEFAULT 'active',
    `start_date` DATE NULL DEFAULT NULL,
    `end_date` DATE NULL DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_campaigns_shop_platform_cid` (`shop_id`, `platform_campaign_id`),
    INDEX `idx_campaigns_tenant_id` (`tenant_id`),
    CONSTRAINT `fk_campaigns_tenant_id` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_campaigns_shop_id` FOREIGN KEY (`shop_id`) REFERENCES `shops` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- Table: ad_groups
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `ad_groups` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `campaign_id` BIGINT UNSIGNED NOT NULL,
    `platform_group_id` VARCHAR(100) NULL DEFAULT NULL,
    `listing_id` BIGINT UNSIGNED NULL DEFAULT NULL,
    `name` VARCHAR(200) NOT NULL,
    `bid` DECIMAL(10,2) NULL DEFAULT NULL,
    `status` ENUM('active','paused','archived') NOT NULL DEFAULT 'active',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_ad_groups_tenant_id` (`tenant_id`),
    INDEX `idx_ad_groups_campaign_id` (`campaign_id`),
    CONSTRAINT `fk_ad_groups_tenant_id` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_ad_groups_campaign_id` FOREIGN KEY (`campaign_id`) REFERENCES `ad_campaigns` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- Table: ad_keywords
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `ad_keywords` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `ad_group_id` BIGINT UNSIGNED NOT NULL,
    `keyword` VARCHAR(200) NOT NULL,
    `match_type` ENUM('exact','phrase','broad') NOT NULL DEFAULT 'broad',
    `bid` DECIMAL(10,2) NULL DEFAULT NULL,
    `is_negative` TINYINT(1) NOT NULL DEFAULT 0,
    `status` ENUM('active','paused','deleted') NOT NULL DEFAULT 'active',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_ad_keywords_tenant_id` (`tenant_id`),
    INDEX `idx_ad_keywords_ad_group_id` (`ad_group_id`),
    CONSTRAINT `fk_ad_keywords_tenant_id` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_ad_keywords_ad_group_id` FOREIGN KEY (`ad_group_id`) REFERENCES `ad_groups` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- Table: ad_stats
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `ad_stats` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `campaign_id` BIGINT UNSIGNED NOT NULL,
    `ad_group_id` BIGINT UNSIGNED NULL DEFAULT NULL,
    `keyword_id` BIGINT UNSIGNED NULL DEFAULT NULL,
    `platform` ENUM('wb','ozon','yandex') NOT NULL,
    `stat_date` DATE NOT NULL,
    `stat_hour` TINYINT NULL DEFAULT NULL,
    `impressions` INT NOT NULL DEFAULT 0,
    `clicks` INT NOT NULL DEFAULT 0,
    `spend` DECIMAL(10,2) NOT NULL DEFAULT 0,
    `orders` INT NOT NULL DEFAULT 0,
    `revenue` DECIMAL(10,2) NOT NULL DEFAULT 0,
    `ctr` DECIMAL(8,4) NULL DEFAULT NULL,
    `cpc` DECIMAL(10,2) NULL DEFAULT NULL,
    `acos` DECIMAL(8,4) NULL DEFAULT NULL,
    `roas` DECIMAL(8,4) NULL DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_ad_stats_campaign_date` (`campaign_id`, `stat_date`),
    INDEX `idx_ad_stats_tenant_platform_date` (`tenant_id`, `platform`, `stat_date`),
    CONSTRAINT `fk_ad_stats_tenant_id` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_ad_stats_campaign_id` FOREIGN KEY (`campaign_id`) REFERENCES `ad_campaigns` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
