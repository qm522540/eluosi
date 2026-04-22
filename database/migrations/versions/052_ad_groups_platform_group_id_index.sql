-- 052: ad_groups 加 (campaign_id, platform_group_id) 组合索引
-- 用户报 2026-04-22：早上爬山法上线后，AI 调价"建议列表"接口很慢
-- nginx access log 显示 GET /suggestions/{shop_id} 反复 499（客户端 abort）
--
-- 根因：/suggestions API 的 SQL 包含
--   LEFT JOIN ad_groups ag
--     ON ag.tenant_id = s.tenant_id
--    AND ag.campaign_id = s.campaign_id
--    AND ag.platform_group_id = s.platform_sku_id
-- 但 ad_groups 表只有单字段索引（tenant_id, campaign_id, listing_id），
-- 没有 platform_group_id 索引；今天写入 27 行 hill_* 数据后，MySQL 可能
-- 重选执行计划走全表扫描。
--
-- 加 (campaign_id, platform_group_id) 组合索引覆盖该 JOIN，毫秒级响应。

ALTER TABLE ad_groups
    ADD INDEX idx_camp_pgid (campaign_id, platform_group_id);
