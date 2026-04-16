-- 031: ad_campaigns 加 payment_type 字段区分付费方式
-- CPM=按1000曝光付费, CPC=按点击付费, CPO=按订单付费
-- WB: 主要是 CPM (auction) 和 CPC (search 类型)
-- Ozon: CPC 和 CPO 为主
-- 用于广告列表显示"付费类型"列，关键词管理也只在 CPC 类型才有

ALTER TABLE ad_campaigns
    ADD COLUMN payment_type ENUM('cpm', 'cpc', 'cpo') DEFAULT 'cpm'
    COMMENT 'CPM=按曝光/CPC=按点击/CPO=按订单';

-- 已有数据：WB auction 默认 CPM；Ozon 默认 CPC
UPDATE ad_campaigns SET payment_type = 'cpm' WHERE platform = 'wb';
UPDATE ad_campaigns SET payment_type = 'cpc' WHERE platform = 'ozon';
