-- 024: 删除 ad_stats 表中不再使用的 5 个衍生指标字段
-- 背景:
--   AI 智能调价内部 _query_sku_history 会从 spend/impressions/clicks/orders/revenue
--   重新计算 CTR/CPC/ACOS/ROAS, DB 存这些字段是冗余。
--   stat_hour 一直存 NULL(WB/Ozon 都是日级数据, 无小时维度)。
--   Excel 下载已同步去掉这 6 列展示。
-- 风险: 老代码如果还查这些字段会报错(已确认 ad_tasks.py._upsert_stat 的 stat_hour 引用已移除)

ALTER TABLE ad_stats
  DROP COLUMN stat_hour,
  DROP COLUMN ctr,
  DROP COLUMN cpc,
  DROP COLUMN acos,
  DROP COLUMN roas;
