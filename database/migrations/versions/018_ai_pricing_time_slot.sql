-- 018: AI调价建议表新增时段信息字段
-- 记录触发调价时的莫斯科时段和小时数

ALTER TABLE ai_pricing_suggestions
ADD COLUMN time_slot VARCHAR(50) DEFAULT NULL COMMENT '触发时段名称(上午高峰/晚间高峰/低谷期等)',
ADD COLUMN moscow_hour INT DEFAULT NULL COMMENT '触发时莫斯科小时数(0-23)';
