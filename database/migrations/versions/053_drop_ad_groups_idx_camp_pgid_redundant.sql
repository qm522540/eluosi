-- 053: DROP ad_groups.idx_camp_pgid —— 与 uk_campaign_sku UNIQUE 同字段冗余
--
-- 起因：052 给 ad_groups 加 (campaign_id, platform_group_id) 普通索引修慢查询。
-- 事后 review 发现 uk_campaign_sku UNIQUE 早就存在（同字段同顺序），普通索引完全冗余。
--
-- EXPLAIN 生产验证（2026-04-23）：
--   默认：      LEFT JOIN ad_groups 走 key=uk_campaign_sku, type=eq_ref, rows=1
--   IGNORE idx_camp_pgid：同样走 uk_campaign_sku，行为完全一致
-- 结论：优化器本就选 UNIQUE 索引，idx_camp_pgid 一直未被使用。
--
-- UNIQUE 索引对查询优化器等价于普通索引 + 唯一约束；删除只影响写入时的索引维护开销（降低）。

ALTER TABLE ad_groups DROP INDEX idx_camp_pgid;
