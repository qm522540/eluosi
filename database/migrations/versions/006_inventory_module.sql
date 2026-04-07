-- Migration: 006_inventory_module.sql
-- Author: 老林
-- Date: 2026-04-07
-- Description: Create inventory_stocks, purchase_orders, purchase_order_items tables

SET NAMES utf8mb4;

-- -----------------------------------------------------------
-- Table: inventory_stocks
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `inventory_stocks` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `product_id` BIGINT UNSIGNED NOT NULL,
    `shop_id` BIGINT UNSIGNED NULL DEFAULT NULL,
    `warehouse_name` VARCHAR(100) NULL DEFAULT NULL,
    `quantity` INT NOT NULL DEFAULT 0,
    `reserved` INT NOT NULL DEFAULT 0,
    `min_threshold` INT NOT NULL DEFAULT 10,
    `max_threshold` INT NOT NULL DEFAULT 1000,
    `last_synced_at` DATETIME NULL DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_inv_stocks_tenant_id` (`tenant_id`),
    INDEX `idx_inv_stocks_product_id` (`product_id`),
    INDEX `idx_inv_stocks_shop_id` (`shop_id`),
    CONSTRAINT `fk_inv_stocks_tenant_id` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_inv_stocks_product_id` FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- Table: purchase_orders
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `purchase_orders` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `po_number` VARCHAR(50) NOT NULL,
    `supplier_name` VARCHAR(200) NULL DEFAULT NULL,
    `total_amount` DECIMAL(10,2) NOT NULL DEFAULT 0,
    `currency` VARCHAR(3) NOT NULL DEFAULT 'CNY',
    `status` ENUM('draft','pending','approved','ordered','received','cancelled') NOT NULL DEFAULT 'draft',
    `expected_date` DATE NULL DEFAULT NULL,
    `notes` TEXT NULL DEFAULT NULL,
    `created_by` BIGINT UNSIGNED NOT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_po_tenant_number` (`tenant_id`, `po_number`),
    INDEX `idx_po_tenant_id` (`tenant_id`),
    CONSTRAINT `fk_po_tenant_id` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- Table: purchase_order_items
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `purchase_order_items` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `po_id` BIGINT UNSIGNED NOT NULL,
    `product_id` BIGINT UNSIGNED NOT NULL,
    `quantity` INT NOT NULL,
    `unit_price` DECIMAL(10,2) NOT NULL,
    `total_price` DECIMAL(10,2) NOT NULL,
    `received_quantity` INT NOT NULL DEFAULT 0,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_poi_tenant_id` (`tenant_id`),
    INDEX `idx_poi_po_id` (`po_id`),
    INDEX `idx_poi_product_id` (`product_id`),
    CONSTRAINT `fk_poi_tenant_id` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_poi_po_id` FOREIGN KEY (`po_id`) REFERENCES `purchase_orders` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_poi_product_id` FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
