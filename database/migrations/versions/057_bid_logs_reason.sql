-- 057: bid_adjustment_logs 加 reason 字段
--
-- 用户需求（2026-04-23）：调价历史表格鼠标悬停能看到"为什么调成这个价格"。
-- 当前 reason 只在 ai_pricing_suggestions 里，调价成功后没带过来。
-- 加一个 TEXT 字段冗余存决策理由，写日志时从 suggestion 带过来。
--
-- 历史数据 NULL：cutover 前的 bid_adjustment_logs 不带 reason，前端显示"无详细理由"。

ALTER TABLE bid_adjustment_logs
    ADD COLUMN reason TEXT NULL COMMENT '决策理由（从 ai_pricing_suggestions.reason 带过来或分时调价的时段说明）';
