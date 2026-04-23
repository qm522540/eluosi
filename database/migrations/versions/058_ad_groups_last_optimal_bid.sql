-- 058: ad_groups 加 last_optimal_bid 字段
--
-- 2026-04-23 用户反馈：同时段 base 不变 → 每小时 tick 都算出相同 optimal_bid
--   → 每次都调 WB API 浪费配额，失败记录每小时重复写 bidlog 污染历史。
--
-- 例：MSK 10/11/12/13 同属"上午高峰"时段系数 1.10，若 base 那天没动，
--   optimal = base × 1.10 × day_mult 四次都一样；SKU 498605688 三次
--   调 API 都被 WB 拒（advert 32876650 incorrect status），属于典型
--   重复空转。
--
-- 修法：记住上次算出的 optimal，下次 tick 先比，相等就跳过不写 suggestion。
-- 影响面：跨时段（系数变化）或 base 演化后，optimal 会变，不受影响。

ALTER TABLE ad_groups
    ADD COLUMN last_optimal_bid DECIMAL(10,2) NULL
        COMMENT 'AI 上次算出的 optimal_bid，同值则跳过避免同时段重复 analyze';
