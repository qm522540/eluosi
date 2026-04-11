-- 022: 库存联动（店铺级规则 + 平台仓SKU库存 + 执行日志）
--
-- 功能说明：
--   - 店铺级一条规则（开关+两个阈值），监控该店铺下所有广告活动中的商品
--   - 库存<=pause_threshold时自动暂停出价(改为3卢布)并记录原出价
--   - 库存>=resume_threshold时自动恢复为原出价
--   - 两个阈值之间记为alert预警状态

-- ----------------------------------------------------------------
-- 1. 店铺库存联动规则表
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inventory_linkage_rules (
    id INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    tenant_id BIGINT UNSIGNED NOT NULL,
    shop_id BIGINT UNSIGNED NOT NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 0
        COMMENT '是否开启联动: 0=关闭 1=开启',
    pause_threshold INT NOT NULL DEFAULT 10
        COMMENT '暂停阈值: 库存<=此值暂停该SKU出价',
    resume_threshold INT NOT NULL DEFAULT 20
        COMMENT '恢复阈值: 库存>=此值恢复该SKU出价',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_shop_id (shop_id),
    INDEX idx_tenant_id (tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='店铺级库存联动规则';


-- ----------------------------------------------------------------
-- 2. 平台仓SKU库存表（定时从Ozon同步）
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inventory_platform_stocks (
    id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    tenant_id BIGINT UNSIGNED NOT NULL,
    shop_id BIGINT UNSIGNED NOT NULL,
    campaign_id BIGINT UNSIGNED NOT NULL
        COMMENT '首次关联的广告活动ID (ad_campaigns.id)',
    platform_sku_id VARCHAR(100) NOT NULL
        COMMENT '平台SKU (Ozon数字SKU)',
    sku_name VARCHAR(300) DEFAULT NULL
        COMMENT '商品名称',
    quantity INT NOT NULL DEFAULT 0
        COMMENT '当前平台仓总库存数量',
    status ENUM('normal','alert','paused') NOT NULL DEFAULT 'normal'
        COMMENT '联动状态: normal=正常 alert=预警 paused=已暂停出价',
    last_synced_at DATETIME DEFAULT NULL COMMENT '最后同步时间',
    paused_at DATETIME DEFAULT NULL COMMENT '暂停时间',
    paused_bid DECIMAL(10,2) DEFAULT NULL COMMENT '暂停前的出价(卢布，用于恢复)',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_shop_sku (shop_id, platform_sku_id),
    INDEX idx_shop_status (shop_id, status),
    INDEX idx_campaign_id (campaign_id),
    INDEX idx_tenant_id (tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='平台仓SKU库存快照';


-- ----------------------------------------------------------------
-- 3. 库存联动执行日志
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inventory_linkage_logs (
    id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    tenant_id BIGINT UNSIGNED NOT NULL,
    shop_id BIGINT UNSIGNED NOT NULL,
    campaign_id BIGINT UNSIGNED NOT NULL,
    platform_sku_id VARCHAR(100) NOT NULL,
    sku_name VARCHAR(300) DEFAULT NULL,
    action ENUM('pause','resume','alert') NOT NULL COMMENT '执行动作',
    old_quantity INT DEFAULT 0 COMMENT '触发时库存',
    old_bid DECIMAL(10,2) DEFAULT NULL COMMENT '操作前出价',
    new_bid DECIMAL(10,2) DEFAULT NULL COMMENT '操作后出价',
    success TINYINT(1) NOT NULL DEFAULT 1,
    error_msg VARCHAR(500) DEFAULT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_shop_created (shop_id, created_at),
    INDEX idx_tenant_id (tenant_id),
    INDEX idx_sku_id (platform_sku_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='库存联动执行日志';


-- ----------------------------------------------------------------
-- 4. 为所有现有Ozon店铺创建默认规则记录（关闭状态）
-- ----------------------------------------------------------------
INSERT IGNORE INTO inventory_linkage_rules
    (tenant_id, shop_id, is_active, pause_threshold, resume_threshold)
SELECT tenant_id, id, 0, 10, 20
FROM shops
WHERE platform = 'ozon';
