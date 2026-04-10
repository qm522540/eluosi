-- 021: 数据采集机制简化 — 按天同步 + 首次初始化

-- 1. ad_stats表新增is_final字段（updated_at已存在跳过）
ALTER TABLE ad_stats
    ADD COLUMN is_final TINYINT(1) DEFAULT 1
        COMMENT '是否为日结最终数据';

-- 2. 新增店铺数据初始化状态表
CREATE TABLE IF NOT EXISTS shop_data_init_status (
    id INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    shop_id BIGINT UNSIGNED NOT NULL,
    tenant_id BIGINT UNSIGNED NOT NULL,
    is_initialized TINYINT(1) DEFAULT 0
        COMMENT '是否已完成首次3个月数据拉取',
    initialized_at DATETIME DEFAULT NULL
        COMMENT '首次初始化完成时间',
    last_sync_date DATE DEFAULT NULL
        COMMENT '最后一次同步的数据日期',
    last_sync_at DATETIME DEFAULT NULL
        COMMENT '最后一次同步执行时间',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_shop_id (shop_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. 为所有现有Ozon店铺创建初始化状态记录
INSERT IGNORE INTO shop_data_init_status (shop_id, tenant_id, is_initialized)
SELECT id, tenant_id, 0 FROM shops WHERE platform = 'ozon';
