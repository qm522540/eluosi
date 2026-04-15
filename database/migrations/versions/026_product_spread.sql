-- Migration: 026_product_spread.sql
-- Author: 老林
-- Date: 2026-04-15
-- Description:
--   商品管理升级
--   1) platform_listings 新增字段
--   2) 新增唯一索引
--   3) 新增铺货记录表 spread_records
--   4) 新增类目映射表 category_mappings
--   5) 新增属性映射表 attribute_mappings
--   6) 新增商品属性表 listing_attributes

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- =====================================================================
-- Step 1: platform_listings 新增字段
-- =====================================================================
ALTER TABLE `platform_listings`
    ADD COLUMN `barcode` VARCHAR(50) DEFAULT NULL
        COMMENT '商品条形码' AFTER `platform_product_id`,
    ADD COLUMN `description_ru` TEXT DEFAULT NULL
        COMMENT '商品俄文描述' AFTER `title_ru`,
    ADD COLUMN `variant_name` VARCHAR(100) DEFAULT NULL
        COMMENT '变体名称，如金色/银色/S码' AFTER `description_ru`,
    ADD COLUMN `variant_attrs` JSON DEFAULT NULL
        COMMENT '变体属性，如{"颜色":"金色","尺寸":"均码"}' AFTER `variant_name`,
    ADD COLUMN `platform_listed_at` DATETIME DEFAULT NULL
        COMMENT '商品在平台的上线时间' AFTER `variant_attrs`,
    ADD COLUMN `oss_images` JSON DEFAULT NULL
        COMMENT 'OSS图片地址列表' AFTER `platform_listed_at`,
    ADD COLUMN `oss_videos` JSON DEFAULT NULL
        COMMENT 'OSS视频地址列表（预留）' AFTER `oss_images`,
    ADD COLUMN `source_listing_id` BIGINT DEFAULT NULL
        COMMENT '铺货来源listing_id，NULL表示原始商品' AFTER `oss_videos`,
    ADD COLUMN `publish_status` ENUM('draft','pending','published')
        NOT NULL DEFAULT 'published'
        COMMENT '发布状态' AFTER `source_listing_id`,
    MODIFY COLUMN `status`
        ENUM('active','inactive','deleted','out_of_stock','blocked')
        NOT NULL DEFAULT 'active'
        COMMENT '在售/停售/已删除/缺货/封禁';

-- =====================================================================
-- Step 2: platform_listings 新增唯一索引
-- =====================================================================
ALTER TABLE `platform_listings`
    ADD UNIQUE KEY `uk_listing` (`tenant_id`, `shop_id`, `platform`, `platform_product_id`);

-- =====================================================================
-- Step 3: 铺货记录表
-- =====================================================================
CREATE TABLE IF NOT EXISTS `spread_records` (
    `id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`      BIGINT UNSIGNED NOT NULL,
    `task_id`        VARCHAR(100) NOT NULL       COMMENT 'Celery任务ID',
    `src_listing_id` BIGINT UNSIGNED NOT NULL    COMMENT '来源listing_id',
    `src_shop_id`    BIGINT UNSIGNED NOT NULL    COMMENT '来源店铺',
    `src_platform`   VARCHAR(20) NOT NULL        COMMENT '来源平台',
    `dst_shop_id`    BIGINT UNSIGNED NOT NULL    COMMENT '目标店铺',
    `dst_platform`   VARCHAR(20) NOT NULL        COMMENT '目标平台',
    `src_barcode`    VARCHAR(50) DEFAULT NULL    COMMENT '原条形码',
    `dst_barcode`    VARCHAR(50) DEFAULT NULL    COMMENT '新条形码',
    `title_ru`       VARCHAR(500) DEFAULT NULL   COMMENT '铺货标题（可能AI改写）',
    `description_ru` TEXT DEFAULT NULL           COMMENT '铺货描述',
    `price`          DECIMAL(10,2) DEFAULT NULL  COMMENT '铺货价格',
    `oss_images`     JSON DEFAULT NULL           COMMENT '图片OSS地址',
    `dst_product_id` VARCHAR(100) DEFAULT NULL   COMMENT '目标平台商品ID（发布后回填）',
    `status`         ENUM('pending','processing','success','failed')
                     NOT NULL DEFAULT 'pending',
    `error_msg`      VARCHAR(500) DEFAULT NULL   COMMENT '失败原因',
    `started_at`     DATETIME DEFAULT NULL,
    `finished_at`    DATETIME DEFAULT NULL,
    `created_at`     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_task`   (`task_id`),
    INDEX `idx_tenant` (`tenant_id`),
    INDEX `idx_src`    (`src_listing_id`),
    INDEX `idx_dst`    (`dst_shop_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='铺货记录表';

-- =====================================================================
-- Step 4: 类目映射表
-- =====================================================================
CREATE TABLE IF NOT EXISTS `category_mappings` (
    `id`                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`         BIGINT UNSIGNED NOT NULL,
    `src_platform`      VARCHAR(20) NOT NULL,
    `src_category_id`   VARCHAR(100) NOT NULL,
    `src_category_name` VARCHAR(200) DEFAULT NULL,
    `dst_platform`      VARCHAR(20) NOT NULL,
    `dst_category_id`   VARCHAR(100) NOT NULL,
    `dst_category_name` VARCHAR(200) DEFAULT NULL,
    `ai_confidence`     TINYINT NOT NULL DEFAULT 0  COMMENT 'AI置信度0-100',
    `is_confirmed`      TINYINT NOT NULL DEFAULT 0  COMMENT '0=待确认 1=已确认',
    `created_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_mapping` (`tenant_id`, `src_platform`, `src_category_id`, `dst_platform`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='类目映射表';

-- =====================================================================
-- Step 5: 属性映射表
-- =====================================================================
CREATE TABLE IF NOT EXISTS `attribute_mappings` (
    `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`       BIGINT UNSIGNED NOT NULL,
    `src_platform`    VARCHAR(20) NOT NULL,
    `dst_platform`    VARCHAR(20) NOT NULL,
    `src_category_id` VARCHAR(100) DEFAULT NULL,
    `dst_category_id` VARCHAR(100) DEFAULT NULL,
    `src_attr_name`   VARCHAR(200) NOT NULL,
    `dst_attr_name`   VARCHAR(200) NOT NULL,
    `src_attr_value`  VARCHAR(200) DEFAULT NULL  COMMENT '为空=所有值通用',
    `dst_attr_value`  VARCHAR(200) DEFAULT NULL,
    `ai_confidence`   TINYINT NOT NULL DEFAULT 0,
    `is_confirmed`    TINYINT NOT NULL DEFAULT 0,
    `created_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_mapping` (`tenant_id`, `src_platform`, `dst_platform`, `src_category_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='属性映射表';

-- =====================================================================
-- Step 6: 商品属性表
-- =====================================================================
CREATE TABLE IF NOT EXISTS `listing_attributes` (
    `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`  BIGINT UNSIGNED NOT NULL,
    `listing_id` BIGINT UNSIGNED NOT NULL,
    `platform`   VARCHAR(20) NOT NULL,
    `attr_name`  VARCHAR(200) NOT NULL,
    `attr_value` VARCHAR(500) DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_listing` (`listing_id`),
    INDEX `idx_tenant`  (`tenant_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='商品属性表';

SET FOREIGN_KEY_CHECKS = 1;
