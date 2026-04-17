-- 041: 关键词效能评级的租户级自定义规则
-- 关键词明细页的"高效/潜力/浪费/普通"分类原本是硬编码阈值
-- （CTR≥5% star / CTR≥3% potential / CTR<1% waste）
-- 现改为租户可配置：每租户一行 rules_json 存 6 项阈值，无记录走代码默认

CREATE TABLE IF NOT EXISTS keyword_efficiency_rules (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_id BIGINT UNSIGNED NOT NULL,
    rules_json JSON NOT NULL COMMENT '6 项阈值：star_ctr_min / star_cpc_max_ratio / potential_ctr_min / potential_impressions_max_ratio / waste_ctr_max / waste_spend_min_ratio',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_tenant (tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    COMMENT='关键词效能评级规则：租户级，无记录走代码默认';
