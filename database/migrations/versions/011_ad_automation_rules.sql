-- 011: 广告自动化规则表
-- 支持自动暂停低ROI活动、自动调价、预算封顶、定时投放

CREATE TABLE IF NOT EXISTS ad_automation_rules (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    name VARCHAR(200) NOT NULL COMMENT '规则名称',
    rule_type ENUM('pause_low_roi', 'auto_bid', 'budget_cap', 'schedule') NOT NULL COMMENT '规则类型',
    conditions JSON DEFAULT NULL COMMENT '触发条件(JSON)',
    actions JSON DEFAULT NULL COMMENT '执行动作(JSON)',
    platform VARCHAR(20) DEFAULT NULL COMMENT '限定平台: wb/ozon/yandex',
    campaign_id BIGINT DEFAULT NULL COMMENT '限定活动ID',
    shop_id BIGINT DEFAULT NULL COMMENT '限定店铺ID',
    enabled SMALLINT NOT NULL DEFAULT 1 COMMENT '0=禁用, 1=启用',
    last_triggered_at DATETIME DEFAULT NULL COMMENT '最后触发时间',
    trigger_count INT NOT NULL DEFAULT 0 COMMENT '累计触发次数',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_tenant (tenant_id),
    INDEX idx_enabled (tenant_id, enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='广告自动化规则';
