-- 020: 大促日历表 + 商品阶段字段 + 大促数据隔离表

-- 1. 大促日历表
CREATE TABLE IF NOT EXISTS promo_calendars (
    id INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    tenant_id BIGINT UNSIGNED NOT NULL,
    promo_name VARCHAR(100) NOT NULL COMMENT '大促名称',
    promo_date DATE NOT NULL COMMENT '大促当天日期',
    pre_heat_days INT DEFAULT 1 COMMENT '预热天数',
    recovery_days INT DEFAULT 3 COMMENT '恢复天数',
    pre_heat_multiplier DECIMAL(4,2) DEFAULT 1.30 COMMENT '预热期出价系数',
    peak_multiplier DECIMAL(4,2) DEFAULT 1.70 COMMENT '大促当天出价系数',
    recovery_day1_multiplier DECIMAL(4,2) DEFAULT 0.90 COMMENT '恢复第1天系数',
    recovery_day2_multiplier DECIMAL(4,2) DEFAULT 0.95 COMMENT '恢复第2天系数',
    recovery_day3_multiplier DECIMAL(4,2) DEFAULT 1.00 COMMENT '恢复第3天系数',
    is_active TINYINT(1) DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. 内置俄罗斯主要大促节日
INSERT INTO promo_calendars
(tenant_id, promo_name, promo_date, pre_heat_multiplier, peak_multiplier) VALUES
(4, '元旦', '2026-01-01', 1.30, 1.80),
(4, '情人节', '2026-02-14', 1.25, 1.60),
(4, '妇女节', '2026-03-08', 1.40, 2.00),
(4, '劳动节', '2026-05-01', 1.20, 1.50),
(4, '黑色星期五', '2026-11-27', 1.50, 2.00),
(4, '双十二', '2026-12-12', 1.30, 1.70),
(4, '新年前夕', '2026-12-31', 1.40, 1.80);

-- 3. 大促数据隔离表
CREATE TABLE IF NOT EXISTS ad_stats_promo (
    id INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    tenant_id BIGINT UNSIGNED NOT NULL,
    campaign_id BIGINT UNSIGNED NOT NULL,
    stat_date DATE NOT NULL,
    promo_name VARCHAR(100) COMMENT '对应大促名称',
    promo_phase ENUM('pre_heat','peak','recovery') COMMENT '大促阶段',
    impressions INT DEFAULT 0,
    clicks INT DEFAULT 0,
    ctr DECIMAL(5,2) DEFAULT NULL,
    cpm DECIMAL(10,2) DEFAULT NULL,
    spend DECIMAL(10,2) DEFAULT 0,
    orders INT DEFAULT 0,
    cr DECIMAL(5,2) DEFAULT NULL,
    revenue DECIMAL(10,2) DEFAULT 0,
    roas DECIMAL(5,2) DEFAULT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_campaign_date (campaign_id, stat_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. ai_pricing_suggestions新增阶段字段
ALTER TABLE ai_pricing_suggestions
    ADD COLUMN product_stage VARCHAR(50) DEFAULT 'unknown' COMMENT '商品生命周期阶段',
    ADD COLUMN stage_optimize_target VARCHAR(50) DEFAULT NULL COMMENT '本阶段主导优化目标',
    ADD COLUMN promo_phase VARCHAR(50) DEFAULT NULL COMMENT '大促阶段',
    ADD COLUMN promo_multiplier DECIMAL(4,2) DEFAULT 1.00 COMMENT '大促出价系数';

-- 5. ai_pricing_configs新增优化目标字段
ALTER TABLE ai_pricing_configs
    ADD COLUMN optimize_target VARCHAR(50) DEFAULT 'auto' COMMENT '主导优化目标';
