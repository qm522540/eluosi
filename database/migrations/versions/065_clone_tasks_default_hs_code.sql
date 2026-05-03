-- 065_clone_tasks_default_hs_code.sql
-- 2026-05-03 老林 — 克隆任务加默认 HS 编码字段
-- 业务: B 店商品 attributes 里若缺 ТН ВЭД (HS code, attr_id=22232 必填),
--      publish 到 A 店时用 task.default_hs_code 强制注入, 否则 Ozon 拒收.
-- 老板拍: "我们饰品的HS编码是711719000，其他类目会不一样"
-- attr_id=22232 是耳环类目验证过的, 其他类目可能不同, 暂硬编码看后续是否需要拆 attr_id.

ALTER TABLE clone_tasks
  ADD COLUMN default_hs_code VARCHAR(30) NULL DEFAULT NULL
  COMMENT 'A 店类目默认 HS 编码 (ТН ВЭД, 例如饰品=711719000); publish 时若 B 店 attributes 缺 attr_id=22232 则强制注入';
