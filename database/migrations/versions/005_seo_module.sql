-- Migration: 005_seo_module.sql
-- Author: 老林
-- Date: 2026-04-07
-- Description: Create seo_keywords, seo_templates, seo_generated_contents tables

SET NAMES utf8mb4;

-- -----------------------------------------------------------
-- Table: seo_keywords
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `seo_keywords` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `platform` ENUM('wb','ozon','yandex') NOT NULL,
    `keyword_ru` VARCHAR(200) NOT NULL,
    `keyword_zh` VARCHAR(200) NULL DEFAULT NULL,
    `search_volume` INT NULL DEFAULT NULL,
    `competition` ENUM('low','medium','high') NULL DEFAULT NULL,
    `category` VARCHAR(200) NULL DEFAULT NULL,
    `source` ENUM('platform','manual','ai_suggested') NOT NULL DEFAULT 'manual',
    `status` ENUM('active','inactive') NOT NULL DEFAULT 'active',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_seo_keywords_tenant_id` (`tenant_id`),
    INDEX `idx_seo_keywords_platform` (`platform`),
    CONSTRAINT `fk_seo_keywords_tenant_id` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- Table: seo_templates
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `seo_templates` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `platform` ENUM('wb','ozon','yandex') NOT NULL,
    `category` VARCHAR(200) NOT NULL,
    `template_type` ENUM('title','description','bullet_points','rich_content') NOT NULL,
    `template_text` TEXT NOT NULL,
    `language` VARCHAR(5) NOT NULL DEFAULT 'ru',
    `status` ENUM('active','inactive') NOT NULL DEFAULT 'active',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_seo_templates_tenant_id` (`tenant_id`),
    INDEX `idx_seo_templates_platform_category` (`platform`, `category`),
    CONSTRAINT `fk_seo_templates_tenant_id` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- Table: seo_generated_contents
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `seo_generated_contents` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `listing_id` BIGINT UNSIGNED NOT NULL,
    `content_type` ENUM('title','description','bullet_points','rich_content') NOT NULL,
    `original_text` TEXT NULL DEFAULT NULL,
    `generated_text` TEXT NOT NULL,
    `keywords_used` JSON NULL DEFAULT NULL,
    `ai_model` ENUM('deepseek','kimi','glm') NOT NULL,
    `ai_decision_id` BIGINT UNSIGNED NULL DEFAULT NULL,
    `approval_status` ENUM('pending','approved','rejected','applied') NOT NULL DEFAULT 'pending',
    `approved_by` BIGINT UNSIGNED NULL DEFAULT NULL,
    `applied_at` DATETIME NULL DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_seo_generated_tenant_id` (`tenant_id`),
    INDEX `idx_seo_generated_listing_id` (`listing_id`),
    CONSTRAINT `fk_seo_generated_tenant_id` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_seo_generated_listing_id` FOREIGN KEY (`listing_id`) REFERENCES `platform_listings` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
