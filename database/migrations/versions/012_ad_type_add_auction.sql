-- 012: ad_type枚举新增auction类型（WB type 9 = 竞价/CPM广告）
ALTER TABLE ad_campaigns MODIFY COLUMN ad_type ENUM('search', 'catalog', 'product_page', 'recommendation', 'auction') NOT NULL;
