-- Migration: 050_ad_groups_hill_climbing.sql
-- Author: 老林
-- Date: 2026-04-21
-- Description:
--   方案 E 爬山法所需的 SKU 级状态字段，存在 ad_groups 表里。
--   每个 (campaign_id, platform_group_id) 组合一条记录。
--
--   字段：
--     hill_base_bid       — 爬山法 base 价（甜点价锚点），实际出价 = base × 时段系数 × 周末系数
--     hill_step_direction — 上次爬山方向 +1=涨 / -1=跌 / 0=持平（NULL=未启用）
--     hill_step_size      — 当前步长 0.20/0.10/0.05/0.02（几何减半收敛）
--     hill_last_eval_at   — 上次爬山评估时间（每天滑动评估一次）
--
--   触发条件：data_days >= 21 的 SKU 第一次进算法时冷启动写入。
--   < 21 天的 SKU 仍走老 _profit_max_decision（已被 04-21 Bug fix 修过）。

SET NAMES utf8mb4;

ALTER TABLE `ad_groups`
    ADD COLUMN `hill_base_bid` DECIMAL(10,2) DEFAULT NULL
        COMMENT '爬山法 base 价（甜点价锚点），实际出价 = base × 时段系数 × 周末系数',
    ADD COLUMN `hill_step_direction` TINYINT DEFAULT NULL
        COMMENT '上次爬山方向 +1=涨 / -1=跌 / 0=持平',
    ADD COLUMN `hill_step_size` DECIMAL(4,2) DEFAULT NULL
        COMMENT '当前步长 0.20/0.10/0.05/0.02（几何减半收敛）',
    ADD COLUMN `hill_last_eval_at` DATETIME DEFAULT NULL
        COMMENT '上次爬山评估时间';
