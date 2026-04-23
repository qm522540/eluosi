-- 056: AI 调价 Day 1-20 新机制独立字段
--
-- 背景（2026-04-23 老林重构）：
-- 原 _profit_max_decision 对 <21 天商品使用 current_bid 作为基准，每小时 beat
-- 都用"实时平台价 × multiplier"累积调整，导致价格雪崩（小亏连续 -15% 能一晚
-- 从 ₽30 降到 ₽12）。新机制引入独立 base 锚点，每天只动 1 次 base，剩余 23 小时
-- 只重算 base × 时段 × 星期。
--
-- 字段语义：
-- - first_seen_bid:     Day 1 AI 第一次见到该 SKU 时的平台出价快照（永不改）
-- - early_base_bid:     Day 1-20 AI 维护的 base（每天演化：+3% / ±5% / +10% 等）
-- - early_last_eval_at: Day 1-20 上次评估时间（一天一评护栏，按莫斯科自然日切换）
--
-- 边界约束：
-- - hill_* 字段（Day 21+ 爬山法用）**绝对不碰**
-- - Day 21 爬山法第一次跑仍走 cold_start 分支（hill_base_bid is NULL）
-- - Day 20→21 会有策略跳变（用户拍了可接受）

ALTER TABLE ad_groups
    ADD COLUMN first_seen_bid     DECIMAL(10,2) NULL COMMENT 'AI 第一次见该 SKU 时的平台出价（Day 1 锚，永不改）',
    ADD COLUMN early_base_bid     DECIMAL(10,2) NULL COMMENT 'Day 1-20 AI 维护的 base（每天演化）',
    ADD COLUMN early_last_eval_at DATETIME      NULL COMMENT 'Day 1-20 上次评估时间（一天一评护栏）';
