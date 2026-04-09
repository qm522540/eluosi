-- 013: shops表新增Ozon广告API(Performance)凭证字段
ALTER TABLE shops ADD COLUMN perf_client_id VARCHAR(500) DEFAULT NULL COMMENT 'Ozon广告API Client ID' AFTER oauth_expires_at;
ALTER TABLE shops ADD COLUMN perf_client_secret VARCHAR(500) DEFAULT NULL COMMENT 'Ozon广告API Client Secret' AFTER perf_client_id;
