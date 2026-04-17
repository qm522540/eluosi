-- Migration: 034_region_daily_stats.sql
SET NAMES utf8mb4;
CREATE TABLE IF NOT EXISTS `region_daily_stats` (
    `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`   BIGINT UNSIGNED NOT NULL,
    `shop_id`     BIGINT UNSIGNED NOT NULL,
    `platform`    ENUM('wb','ozon') NOT NULL,
    `region_name` VARCHAR(200) NOT NULL COMMENT '地区名（俄文原文）',
    `stat_date`   DATE NOT NULL,
    `orders`      INT NOT NULL DEFAULT 0,
    `revenue`     DECIMAL(14,2) NOT NULL DEFAULT 0 COMMENT '销售额（卢布）',
    `returns`     INT NOT NULL DEFAULT 0,
    `created_at`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_region_stat` (`tenant_id`, `shop_id`, `region_name`(150), `stat_date`),
    INDEX `idx_shop_date` (`tenant_id`, `shop_id`, `stat_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='地区每日销售统计（90天保留）';
