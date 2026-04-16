-- 027: AI调价 v2 — ad_groups 加 SKU 级动态 cpa_ratio 字段
-- 用于 ≥21天利润试探机制：每3天评估 last3 vs prev3 利润，±0.05 调整

ALTER TABLE ad_groups
    ADD COLUMN cpa_ratio DECIMAL(4,2) DEFAULT NULL COMMENT 'SKU级动态cpa_ratio（≥21天利润试探）',
    ADD COLUMN cpa_ratio_updated DATETIME DEFAULT NULL COMMENT '上次cpa_ratio评估时间';
