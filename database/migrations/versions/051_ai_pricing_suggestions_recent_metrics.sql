-- 051: ai_pricing_suggestions 加近 5 健康天指标，前端 Tooltip 动态展示
-- 用户拍 2026-04-22：商品阶段 Tooltip 要显示 28 天累计 + 近 5 天 CTR/CR/利润对比，
-- 让用户一眼看到"商品最近是否在恶化"
--
-- recent_ctr: 近 5 健康天 CTR = SUM(clicks) / SUM(impressions)
-- recent_cr:  近 5 健康天 CR  = SUM(orders) / SUM(clicks)
-- recent_profit: 近 5 健康天利润 = SUM(revenue) × margin - SUM(spend)
--
-- "健康天" 定义同 _calc_healthy_window_metrics：剔除当天 ROAS>50 或 spend<₽10

ALTER TABLE ai_pricing_suggestions
    ADD COLUMN recent_ctr    DECIMAL(6,4) NULL COMMENT '近 5 健康天 CTR',
    ADD COLUMN recent_cr     DECIMAL(6,4) NULL COMMENT '近 5 健康天 CR',
    ADD COLUMN recent_profit DECIMAL(12,2) NULL COMMENT '近 5 健康天利润（卢布，可负）';
