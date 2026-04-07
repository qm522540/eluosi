-- Migration: 009_notifications.sql
-- Author: 老林
-- Date: 2026-04-07
-- Description: Create notifications table

SET NAMES utf8mb4;

-- -----------------------------------------------------------
-- Table: notifications
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `notifications` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `user_id` BIGINT UNSIGNED NULL DEFAULT NULL,
    `notification_type` ENUM('roi_alert','task_failure','ai_decision','daily_report','stock_alert','system') NOT NULL,
    `title` VARCHAR(200) NOT NULL,
    `content` TEXT NOT NULL,
    `channel` ENUM('wechat_work','in_app','both') NOT NULL DEFAULT 'both',
    `is_read` TINYINT(1) NOT NULL DEFAULT 0,
    `sent_at` DATETIME NULL DEFAULT NULL,
    `read_at` DATETIME NULL DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_notif_tenant_id` (`tenant_id`),
    INDEX `idx_notif_user_id` (`user_id`),
    INDEX `idx_notif_type` (`notification_type`),
    INDEX `idx_notif_is_read` (`is_read`),
    CONSTRAINT `fk_notif_tenant_id` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
