-- 063_clone_tasks_follow_status.sql
-- 店铺克隆 — 加 follow_status_change 字段（跟 B 店上下架）
--
-- 业务语义（老林暂拍, 老板可改）:
--   - B status='inactive' → A 'inactive'      (B 下架 → A 下架)
--   - B 'active'(重新上架) → A 已 published 过的同步 'active'
--   - B 删除商品           → A 标 'inactive' (不删, 留着用户决定)
--
-- 实施分两步:
--   阶段 A (本次): 加字段 + ORM + schemas + 前端 Switch (列表能改这个开关)
--   阶段 B (后续): status_sync 引擎 + Celery beat (实际调 Ozon 上下架 API)
--                  当前阶段 A 部署完, beat 内核占位 TODO 等老板拍 Ozon API 端点
--
-- 类型对齐: TINYINT(1) 默认 0; 跟 follow_price_change 一致
-- 关联文档: daily 2026-05-02 §11.3.2

ALTER TABLE clone_tasks
    ADD COLUMN follow_status_change TINYINT(1) NOT NULL DEFAULT 0
        COMMENT '是否跟 B 店上下架 (0=不跟, 1=B下A下/B上A上/B删A停; status_sync beat 处理)';
