-- 014: 出价调整日志表
CREATE TABLE IF NOT EXISTS ad_bid_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    campaign_id BIGINT NOT NULL,
    platform VARCHAR(20) NOT NULL,
    campaign_name VARCHAR(200) DEFAULT NULL,
    group_id BIGINT DEFAULT NULL,
    group_name VARCHAR(200) DEFAULT NULL,
    old_bid DECIMAL(10,2) NOT NULL,
    new_bid DECIMAL(10,2) NOT NULL,
    change_pct DECIMAL(8,2) NOT NULL,
    reason VARCHAR(200) NOT NULL,
    rule_id BIGINT DEFAULT NULL,
    rule_name VARCHAR(200) DEFAULT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_tenant (tenant_id),
    INDEX idx_campaign (campaign_id),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='出价调整日志';
