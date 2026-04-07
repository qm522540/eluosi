-- Migration: 007_finance_module.sql
-- Author: 老林
-- Date: 2026-04-07
-- Description: Create finance_costs, finance_revenues, finance_roi_snapshots tables

SET NAMES utf8mb4;

-- -----------------------------------------------------------
-- Table: finance_costs
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `finance_costs` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `shop_id` BIGINT UNSIGNED NOT NULL,
    `listing_id` BIGINT UNSIGNED NULL DEFAULT NULL,
    `cost_date` DATE NOT NULL,
    `cost_type` ENUM('ad_spend','logistics','commission','storage','other') NOT NULL,
    `amount` DECIMAL(10,2) NOT NULL,
    `currency` VARCHAR(3) NOT NULL DEFAULT 'RUB',
    `notes` VARCHAR(500) NULL DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_fin_costs_tenant_shop_date` (`tenant_id`, `shop_id`, `cost_date`),
    CONSTRAINT `fk_fin_costs_tenant_id` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_fin_costs_shop_id` FOREIGN KEY (`shop_id`) REFERENCES `shops` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- Table: finance_revenues
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `finance_revenues` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `shop_id` BIGINT UNSIGNED NOT NULL,
    `listing_id` BIGINT UNSIGNED NULL DEFAULT NULL,
    `revenue_date` DATE NOT NULL,
    `orders_count` INT NOT NULL DEFAULT 0,
    `revenue` DECIMAL(10,2) NOT NULL DEFAULT 0,
    `returns_count` INT NOT NULL DEFAULT 0,
    `returns_amount` DECIMAL(10,2) NOT NULL DEFAULT 0,
    `net_revenue` DECIMAL(10,2) NOT NULL DEFAULT 0,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_fin_rev_tenant_shop_date` (`tenant_id`, `shop_id`, `revenue_date`),
    CONSTRAINT `fk_fin_rev_tenant_id` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_fin_rev_shop_id` FOREIGN KEY (`shop_id`) REFERENCES `shops` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------
-- Table: finance_roi_snapshots
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `finance_roi_snapshots` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `shop_id` BIGINT UNSIGNED NOT NULL,
    `snapshot_date` DATE NOT NULL,
    `period` ENUM('daily','weekly','monthly') NOT NULL,
    `total_revenue` DECIMAL(10,2) NOT NULL DEFAULT 0,
    `total_cost` DECIMAL(10,2) NOT NULL DEFAULT 0,
    `ad_spend` DECIMAL(10,2) NOT NULL DEFAULT 0,
    `gross_profit` DECIMAL(10,2) NOT NULL DEFAULT 0,
    `roi` DECIMAL(8,4) NULL DEFAULT NULL,
    `roas` DECIMAL(8,4) NULL DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_roi_snap_tenant_shop_date_period` (`tenant_id`, `shop_id`, `snapshot_date`, `period`),
    CONSTRAINT `fk_roi_snap_tenant_id` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_roi_snap_shop_id` FOREIGN KEY (`shop_id`) REFERENCES `shops` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
