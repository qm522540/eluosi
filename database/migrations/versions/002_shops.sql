-- Migration: 002_shops.sql
-- Author: 老林
-- Date: 2026-04-07
-- Description: Create shops table

SET NAMES utf8mb4;

-- -----------------------------------------------------------
-- Table: shops
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `shops` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `name` VARCHAR(100) NOT NULL,
    `platform` ENUM('wb','ozon','yandex') NOT NULL,
    `platform_seller_id` VARCHAR(100) NULL DEFAULT NULL,
    `api_key` VARCHAR(500) NULL DEFAULT NULL,
    `api_secret` VARCHAR(500) NULL DEFAULT NULL,
    `client_id` VARCHAR(100) NULL DEFAULT NULL,
    `oauth_token` TEXT NULL DEFAULT NULL,
    `oauth_refresh_token` TEXT NULL DEFAULT NULL,
    `oauth_expires_at` DATETIME NULL DEFAULT NULL,
    `currency` VARCHAR(3) NOT NULL DEFAULT 'RUB',
    `timezone` VARCHAR(50) NOT NULL DEFAULT 'Europe/Moscow',
    `status` ENUM('active','inactive','deleted') NOT NULL DEFAULT 'active',
    `last_sync_at` DATETIME NULL DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_shops_tenant_platform` (`tenant_id`, `platform`),
    CONSTRAINT `fk_shops_tenant_id` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
