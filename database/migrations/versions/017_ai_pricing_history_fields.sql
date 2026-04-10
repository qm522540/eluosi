-- 017: AI调价建议表新增历史数据字段
-- 支持记录决策依据、历史ROAS均值、参考天数

ALTER TABLE ai_pricing_suggestions
ADD COLUMN decision_basis VARCHAR(50) DEFAULT 'today_only' COMMENT '决策依据: today_only/history_weighted/budget_control',
ADD COLUMN history_avg_roas DECIMAL(5,2) DEFAULT 0 COMMENT '历史7天平均ROAS',
ADD COLUMN data_days INT DEFAULT 0 COMMENT '参考历史数据天数';
