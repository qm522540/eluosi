-- 037: 全局映射建议表（跨租户共享的"经验"）
-- 跟 tenant 隔离的 category_platform_mappings / attribute_mappings 并存
-- 这里存的是"知识"（WB 14441 叫什么、对应 Ozon 哪个），
-- 租户表里存的是"决策"（我决定叫什么、我决定怎么绑）
-- 所有 hints 表不带 tenant_id，任何租户都能读

-- 单平台分类建议：大家怎么叫这个平台分类
CREATE TABLE IF NOT EXISTS global_category_hints (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    platform VARCHAR(16) NOT NULL COMMENT 'wb | ozon | yandex',
    platform_category_id VARCHAR(100) NOT NULL,
    platform_category_name_ru VARCHAR(500) DEFAULT NULL,
    suggested_local_name_zh VARCHAR(200) DEFAULT NULL
        COMMENT '目前最多确认的本地中文名（lossy：冲突名只留 top1）',
    top_name_count INT NOT NULL DEFAULT 0 COMMENT 'top name 的确认次数',
    total_confirmed_count INT NOT NULL DEFAULT 0 COMMENT '总确认次数（含不同名）',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_platform_cat (platform, platform_category_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    COMMENT='全局平台分类建议（跨租户共享）';

-- 跨平台分类共现：当租户把两个平台分类都绑到同一本地分类，记录共现
CREATE TABLE IF NOT EXISTS global_cross_platform_category_hints (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    platform_a VARCHAR(16) NOT NULL COMMENT '按字典序小的平台放前面',
    category_a_id VARCHAR(100) NOT NULL,
    platform_b VARCHAR(16) NOT NULL,
    category_b_id VARCHAR(100) NOT NULL,
    co_confirmed_count INT NOT NULL DEFAULT 0 COMMENT '共现确认次数',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_pair (platform_a, category_a_id, platform_b, category_b_id),
    KEY idx_lookup (platform_a, category_a_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    COMMENT='全局跨平台分类共现建议';

-- 单平台属性建议：大家怎么叫这个平台属性（不按 category 隔离，attr_id 在平台内唯一）
CREATE TABLE IF NOT EXISTS global_attribute_hints (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    platform VARCHAR(16) NOT NULL,
    platform_attr_id VARCHAR(100) NOT NULL,
    platform_attr_name_ru VARCHAR(500) DEFAULT NULL,
    suggested_local_name_zh VARCHAR(200) DEFAULT NULL,
    top_name_count INT NOT NULL DEFAULT 0,
    total_confirmed_count INT NOT NULL DEFAULT 0,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_platform_attr (platform, platform_attr_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    COMMENT='全局平台属性建议（跨租户共享）';
