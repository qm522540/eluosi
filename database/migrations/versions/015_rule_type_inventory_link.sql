-- 015: rule_type枚举增加inventory_link(库存联动)
ALTER TABLE ad_automation_rules MODIFY COLUMN rule_type ENUM('pause_low_roi', 'auto_bid', 'budget_cap', 'schedule', 'inventory_link') NOT NULL;
