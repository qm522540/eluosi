-- 066_clone_tasks_target_brand_dict_id.sql
-- 2026-05-04 老林 — 持久化 Ozon 品牌字典 dict_id 避免每次 publish 重扫 70k 条字典
-- 业务: target_brand resolve 成功一次, dict_id 写回 task; 下次 publish 直接读字段秒回.
-- 用户改 target_brand 字符串时由 task_service.update_task 自动清 dict_id 触发重 resolve.

ALTER TABLE clone_tasks
  ADD COLUMN target_brand_dict_id BIGINT NULL DEFAULT NULL
  COMMENT 'Ozon 品牌字典 ID (attr_id=85 dictionary_value_id); 首次 publish resolve 后持久化, 改 target_brand 时清空';
