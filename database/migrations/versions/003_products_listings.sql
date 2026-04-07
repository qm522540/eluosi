-- Migration: 003_products_listings.sql
-- Author: 老林
-- Date: 2026-04-07
-- Description: Create products and platform_listings tables

SET NAMES utf8mb4;

-- -----------------------------------------------------------
-- Table: products
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `products` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `sku` VARCHAR(50) NOT NULL,
    `name_zh` VARCHAR(200) NOT NULL,
    `name_ru` VARCHAR(200) NULL DEFAULT NULL,
    `brand` VARCHAR(100) NULL DEFAULT NULL,
    `category` VARCHAR(200) NULL DEFAULT NULL,
    `cost_price` DECIMAL(10,2) NULL DEFAULT NULL,
    `weight_g` INT NULL DEFAULT NULL,
    `image_url` VARCHAR(500) NULL DEFAULT NULL,
    `status` ENUM('active','inactive','deleted') NOT NULL DEFAULT 'active',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_products_tenant_sku` (`tenant_id`, `sku`),
    INDEX `idx_products_tenant_id` (`tenant_id`),
    CONSTRAINT `fk_products_tenant_id` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- Table: platform_listings
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `platform_listings` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `product_id` BIGINT UNSIGNED NOT NULL,
    `shop_id` BIGINT UNSIGNED NOT NULL,
    `platform` ENUM('wb','ozon','yandex') NOT NULL,
    `platform_product_id` VARCHAR(100) NOT NULL,
    `title_ru` VARCHAR(500) NULL DEFAULT NULL,
    `price` DECIMAL(10,2) NULL DEFAULT NULL,
    `discount_price` DECIMAL(10,2) NULL DEFAULT NULL,
    `commission_rate` DECIMAL(5,2) NULL DEFAULT NULL,
    `url` VARCHAR(500) NULL DEFAULT NULL,
    `rating` DECIMAL(3,2) NULL DEFAULT NULL,
    `review_count` INT NOT NULL DEFAULT 0,
    `status` ENUM('active','inactive','deleted','out_of_stock') NOT NULL DEFAULT 'active',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_listings_shop_platform_pid` (`shop_id`, `platform`, `platform_product_id`),
    INDEX `idx_listings_tenant_id` (`tenant_id`),
    INDEX `idx_listings_product_id` (`product_id`),
    CONSTRAINT `fk_listings_tenant_id` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_listings_product_id` FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_listings_shop_id` FOREIGN KEY (`shop_id`) REFERENCES `shops` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
