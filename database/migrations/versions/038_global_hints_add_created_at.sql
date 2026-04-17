-- 038: 补 037 建表时漏的 created_at 字段（ORM BaseMixin 需要）
ALTER TABLE global_category_hints
    ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP AFTER total_confirmed_count;

ALTER TABLE global_cross_platform_category_hints
    ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP AFTER co_confirmed_count;

ALTER TABLE global_attribute_hints
    ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP AFTER total_confirmed_count;
