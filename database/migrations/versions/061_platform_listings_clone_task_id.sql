-- 061_platform_listings_clone_task_id.sql
-- 店铺克隆 — platform_listings 加追溯字段
--
-- 目的: 店铺克隆任务抓取的商品入 platform_listings 草稿 (status='inactive'),
--       需要标记草稿来自哪个 clone_task,用于:
--       - 区分"用户主动停售 inactive" vs "克隆草稿 inactive"
--       - 反向追溯草稿到任务,方便 reject/restore 状态联动
--       - SEO AI 改写接口 (optimize_title / generate_description) 直接复用,
--         零改造 (clone_task_id 是新字段不影响现有查询)
--
-- 不动 status ENUM 设计: 现有 8 处 WHERE status='active' 查询零污染,
-- 草稿用 status='inactive' + clone_task_id IS NOT NULL 双条件区分。
--
-- 规则 6 时间: 本 migration 不涉及业务时间字段
-- 关联文档: docs/api/store_clone.md §3.1

ALTER TABLE platform_listings
    ADD COLUMN clone_task_id INT DEFAULT NULL
        COMMENT '关联 clone_tasks.id; 非 NULL = 克隆草稿; NULL = 普通 listing',
    ADD KEY idx_clone_task (clone_task_id);
