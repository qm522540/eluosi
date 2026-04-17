-- 036: 俄→中翻译字典（跨租户共享）
-- 用于编辑商品抽屉里展示平台属性值的中文翻译
-- 翻译缓存，首次 Kimi 翻译后回写，此后秒读

CREATE TABLE IF NOT EXISTS ru_zh_dict (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    text_ru_hash CHAR(32) NOT NULL COMMENT 'MD5(text_ru) 便于 UNIQUE 索引',
    text_ru VARCHAR(500) NOT NULL COMMENT '俄文原文（超过 500 字不缓存）',
    text_zh VARCHAR(500) NOT NULL COMMENT '中文翻译',
    field_type VARCHAR(32) NOT NULL DEFAULT 'attr_value'
        COMMENT 'attr_name | attr_value | other',
    source VARCHAR(16) NOT NULL DEFAULT 'kimi' COMMENT 'kimi | manual',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_hash_type (text_ru_hash, field_type),
    KEY idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    COMMENT='俄→中翻译字典，全局共享';
