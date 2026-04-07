-- Migration: 010_task_logs.sql
-- Author: 老林
-- Date: 2026-04-07
-- Description: Create task_logs table

SET NAMES utf8mb4;

-- -----------------------------------------------------------
-- Table: task_logs
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `task_logs` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NULL DEFAULT NULL,
    `task_name` VARCHAR(100) NOT NULL,
    `celery_task_id` VARCHAR(255) NULL DEFAULT NULL,
    `params` JSON NULL DEFAULT NULL,
    `status` ENUM('pending','running','success','failed','retrying') NOT NULL DEFAULT 'pending',
    `result` JSON NULL DEFAULT NULL,
    `error_message` TEXT NULL DEFAULT NULL,
    `retry_count` INT NOT NULL DEFAULT 0,
    `started_at` DATETIME NULL DEFAULT NULL,
    `finished_at` DATETIME NULL DEFAULT NULL,
    `duration_ms` INT NULL DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_task_logs_tenant_id` (`tenant_id`),
    INDEX `idx_task_logs_task_name` (`task_name`),
    INDEX `idx_task_logs_status` (`status`),
    INDEX `idx_task_logs_celery_id` (`celery_task_id`),
    INDEX `idx_task_logs_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
