-- 019: AI调价重构 — 品类配置→策略模板 + 活动关联 + 建议补充字段

-- 1. ai_pricing_configs表改造：品类→策略模板
ALTER TABLE ai_pricing_configs
  CHANGE category_name template_name VARCHAR(100) COMMENT '策略模板名称',
  ADD COLUMN template_type ENUM('default','conservative','aggressive','custom')
    DEFAULT 'default' COMMENT '模板类型' AFTER template_name,
  ADD COLUMN description VARCHAR(200) DEFAULT NULL
    COMMENT '模板说明' AFTER template_type,
  ADD COLUMN no_budget_limit TINYINT(1) DEFAULT 0
    COMMENT '是否不设预算上限' AFTER daily_budget_limit;

-- 2. 清除旧数据，插入三个标准模板
DELETE FROM ai_pricing_configs;

INSERT INTO ai_pricing_configs
(tenant_id, shop_id, template_name, template_type,
 target_roas, min_roas, gross_margin,
 daily_budget_limit, no_budget_limit,
 max_bid, min_bid, max_adjust_pct,
 auto_execute, is_active, description)
VALUES
(1, 1, '默认标准', 'default',
 3.0, 1.8, 0.50,
 2000.00, 0,
 180.00, 3.00, 30.00,
 0, 1, '默认模板，所有活动未指定时使用此配置'),
(1, 1, '保守测试', 'conservative',
 2.0, 1.5, 0.50,
 500.00, 0,
 100.00, 3.00, 15.00,
 0, 1, '新品冷启动、测试期使用，控制预算风险'),
(1, 1, '激进冲量', 'aggressive',
 4.0, 2.5, 0.50,
 9999.00, 1,
 300.00, 3.00, 25.00,
 0, 1, '已验证爆款、大促期使用，不设预算上限');

-- 3. ad_campaigns表新增模板关联字段
ALTER TABLE ad_campaigns
  ADD COLUMN pricing_config_id INT UNSIGNED DEFAULT NULL
    COMMENT '关联调价策略模板ID，NULL时使用默认模板',
  ADD COLUMN custom_max_bid DECIMAL(10,2) DEFAULT NULL
    COMMENT '单活动覆盖最高出价',
  ADD COLUMN custom_daily_budget DECIMAL(10,2) DEFAULT NULL
    COMMENT '单活动覆盖日预算',
  ADD COLUMN custom_target_roas DECIMAL(5,2) DEFAULT NULL
    COMMENT '单活动覆盖目标ROAS';

-- 4. ai_pricing_suggestions表补充字段（跳过已有的history_avg_roas/data_days/decision_basis/time_slot/moscow_hour）
ALTER TABLE ai_pricing_suggestions
  ADD COLUMN template_name VARCHAR(100) DEFAULT NULL
    COMMENT '执行时使用的模板名称',
  ADD COLUMN data_source VARCHAR(50) DEFAULT 'today_only'
    COMMENT '数据来源描述',
  ADD COLUMN campaign_data_days INT DEFAULT 0
    COMMENT '活动历史数据天数',
  ADD COLUMN is_new_campaign TINYINT(1) DEFAULT 0
    COMMENT '是否为新活动（数据不足）',
  ADD COLUMN shop_avg_roas DECIMAL(5,2) DEFAULT 0
    COMMENT '店铺同期平均ROAS';
