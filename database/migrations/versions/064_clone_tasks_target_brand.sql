-- 064_clone_tasks_target_brand.sql
-- 2026-05-03 老林 — 克隆任务加 A 店品牌名字段
-- 业务: 克隆 B 店商品到 A 店时, 自动把 attributes.品牌 替换为本店品牌,
--      同时从 title_ru / description_ru 里去除 B 店原品牌名.

ALTER TABLE clone_tasks
  ADD COLUMN target_brand VARCHAR(100) NULL DEFAULT NULL
  COMMENT 'A 店品牌名 — publish 时覆盖 attributes attr_id=85 (Бренд) + 标题/描述去除 B 店原品牌名; NULL=不替换';
