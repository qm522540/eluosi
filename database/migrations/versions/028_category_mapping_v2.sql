-- Migration: 028_category_mapping_v2.sql
-- Author: 老张
-- Date: 2026-04-16
-- Description:
--   映射管理 v2：本地统一分类 → 各平台分类/属性/属性值
--   替代 026 的 category_mappings + attribute_mappings（平台对平台设计）
--   新增本地统一分类树 + 三层映射体系 + AI 推荐字段
--
--   1) 新增 local_categories（本地统一分类树）
--   2) 新增 category_platform_mappings（品类映射：本地 → 各平台）
--   3) 重建 attribute_mappings（属性映射：本地属性 → 各平台属性）
--   4) 新增 attribute_value_mappings（属性值映射：本地值 → 各平台枚举值）
--   5) platform_listings 加 platform_category_id / platform_category_name

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- =====================================================================
-- Step 1: 本地统一分类树
-- =====================================================================
CREATE TABLE IF NOT EXISTS `local_categories` (
    `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`   BIGINT UNSIGNED NOT NULL,
    `parent_id`   BIGINT UNSIGNED DEFAULT NULL   COMMENT '父分类ID，NULL=顶级',
    `name`        VARCHAR(200) NOT NULL           COMMENT '分类名称（中文）',
    `name_ru`     VARCHAR(200) DEFAULT NULL       COMMENT '分类名称（俄文，AI翻译）',
    `level`       TINYINT NOT NULL DEFAULT 1      COMMENT '层级：1=一级 2=二级 3=三级',
    `sort_order`  INT NOT NULL DEFAULT 0          COMMENT '同级排序',
    `status`      ENUM('active','inactive') NOT NULL DEFAULT 'active',
    `created_at`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_tenant_parent` (`tenant_id`, `parent_id`),
    INDEX `idx_tenant_level`  (`tenant_id`, `level`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='本地统一分类树（租户级）';

-- =====================================================================
-- Step 2: 品类映射（本地分类 → 各平台分类）
-- =====================================================================
CREATE TABLE IF NOT EXISTS `category_platform_mappings` (
    `id`                      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`               BIGINT UNSIGNED NOT NULL,
    `local_category_id`       BIGINT UNSIGNED NOT NULL  COMMENT '本地分类ID',
    `platform`                VARCHAR(20) NOT NULL      COMMENT 'wb / ozon / yandex',
    `platform_category_id`    VARCHAR(100) NOT NULL     COMMENT '平台分类ID（WB=subjectID, Ozon=type_id）',
    `platform_category_name`  VARCHAR(300) DEFAULT NULL COMMENT '平台分类名称',
    `platform_parent_path`    VARCHAR(500) DEFAULT NULL COMMENT '平台分类面包屑，如 "Одежда > Женская > Платья"',
    `ai_suggested`            TINYINT NOT NULL DEFAULT 0 COMMENT '1=AI推荐 0=人工创建',
    `ai_confidence`           TINYINT NOT NULL DEFAULT 0 COMMENT 'AI置信度0-100',
    `is_confirmed`            TINYINT NOT NULL DEFAULT 0 COMMENT '0=待确认 1=已人工确认',
    `confirmed_at`            DATETIME DEFAULT NULL,
    `created_at`              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_local_platform` (`tenant_id`, `local_category_id`, `platform`),
    INDEX `idx_unconfirmed` (`tenant_id`, `is_confirmed`, `platform`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='品类映射：本地分类→各平台分类';

-- =====================================================================
-- Step 3: 属性映射（本地属性 → 各平台属性）
-- =====================================================================
-- 先删旧表（026 的平台对平台设计，从未使用过）
DROP TABLE IF EXISTS `attribute_mappings`;

CREATE TABLE `attribute_mappings` (
    `id`                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`             BIGINT UNSIGNED NOT NULL,
    `local_category_id`     BIGINT UNSIGNED NOT NULL  COMMENT '所属本地分类',
    `local_attr_name`       VARCHAR(200) NOT NULL     COMMENT '本地属性名（中文）',
    `local_attr_name_ru`    VARCHAR(200) DEFAULT NULL COMMENT '本地属性名（俄文）',
    `platform`              VARCHAR(20) NOT NULL      COMMENT 'wb / ozon / yandex',
    `platform_attr_id`      VARCHAR(100) DEFAULT NULL COMMENT '平台属性ID（WB=charcID, Ozon=attribute_id）',
    `platform_attr_name`    VARCHAR(200) NOT NULL     COMMENT '平台属性名称',
    `is_required`           TINYINT NOT NULL DEFAULT 0 COMMENT '该平台是否必填',
    `value_type`            VARCHAR(20) NOT NULL DEFAULT 'string' COMMENT 'string/enum/number/boolean',
    `platform_dict_id`      VARCHAR(100) DEFAULT NULL COMMENT '平台枚举字典ID（Ozon dictionary_id）',
    `ai_suggested`          TINYINT NOT NULL DEFAULT 0,
    `ai_confidence`         TINYINT NOT NULL DEFAULT 0,
    `is_confirmed`          TINYINT NOT NULL DEFAULT 0,
    `confirmed_at`          DATETIME DEFAULT NULL,
    `created_at`            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_attr_mapping` (`tenant_id`, `local_category_id`, `local_attr_name`, `platform`),
    INDEX `idx_category_platform` (`tenant_id`, `local_category_id`, `platform`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='属性映射：本地属性→各平台属性';

-- =====================================================================
-- Step 4: 属性值映射（本地属性值 → 各平台枚举值）
-- =====================================================================
CREATE TABLE IF NOT EXISTS `attribute_value_mappings` (
    `id`                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`             BIGINT UNSIGNED NOT NULL,
    `attribute_mapping_id`  BIGINT UNSIGNED NOT NULL  COMMENT '所属属性映射ID',
    `local_value`           VARCHAR(500) NOT NULL     COMMENT '本地属性值（中文）',
    `local_value_ru`        VARCHAR(500) DEFAULT NULL COMMENT '本地属性值（俄文）',
    `platform_value`        VARCHAR(500) NOT NULL     COMMENT '平台枚举值文本',
    `platform_value_id`     VARCHAR(100) DEFAULT NULL COMMENT '平台枚举值ID',
    `ai_suggested`          TINYINT NOT NULL DEFAULT 0,
    `ai_confidence`         TINYINT NOT NULL DEFAULT 0,
    `is_confirmed`          TINYINT NOT NULL DEFAULT 0,
    `confirmed_at`          DATETIME DEFAULT NULL,
    `created_at`            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_value_mapping` (`attribute_mapping_id`, `local_value`(100)),
    INDEX `idx_tenant` (`tenant_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='属性值映射：本地属性值→各平台枚举值';

-- =====================================================================
-- Step 5: platform_listings 加平台分类字段
-- =====================================================================
ALTER TABLE `platform_listings`
    ADD COLUMN `platform_category_id`   VARCHAR(100) DEFAULT NULL
        COMMENT '平台分类ID（WB=subjectID, Ozon=description_category_id）' AFTER `platform_product_id`,
    ADD COLUMN `platform_category_name` VARCHAR(300) DEFAULT NULL
        COMMENT '平台分类名称' AFTER `platform_category_id`;

-- =====================================================================
-- Step 6: products 加 local_category_id 关联
-- =====================================================================
ALTER TABLE `products`
    ADD COLUMN `local_category_id` BIGINT UNSIGNED DEFAULT NULL
        COMMENT '本地统一分类ID' AFTER `category`;

-- =====================================================================
-- 旧表 category_mappings 保留不删（有数据的话留着参考），
-- 后续确认无用后再清理
-- =====================================================================

SET FOREIGN_KEY_CHECKS = 1;
