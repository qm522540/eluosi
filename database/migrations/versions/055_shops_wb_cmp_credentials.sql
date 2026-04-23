-- 055: shops 表加 WB CMP (seller-panel) 凭证字段，用于定时抓取「顶级搜索集群」数据
--
-- 背景：2026-04-23 分析用户给的 HAR，cmp.wildberries.ru 内部 API (preset-info + preset/words)
-- 走 authorizev3 JWT + x-supplierid 认证，没有公共 API 可替代。存这两个值后 Celery 可自动
-- 同步，无需用户每次手动上传 xlsx。
--
-- 字段：
--   wb_cmp_authorizev3 — JWT token（~500 字符），用户从 F12 拷贝
--   wb_cmp_supplierid  — 供应商 UUID（36 字符）
--   wb_cmp_token_updated_at — 上次更新 token 的时间（UTC naive）
--   wb_cmp_token_exp_at     — JWT exp 字段解析后的过期时间（UTC naive），过期前 banner 提示

ALTER TABLE shops
    ADD COLUMN wb_cmp_authorizev3      TEXT         NULL COMMENT 'WB cmp.wildberries.ru JWT token',
    ADD COLUMN wb_cmp_supplierid       VARCHAR(64)  NULL COMMENT 'WB supplier UUID (x-supplierid 头)',
    ADD COLUMN wb_cmp_token_updated_at DATETIME     NULL COMMENT 'token 最近更新时间（UTC naive）',
    ADD COLUMN wb_cmp_token_exp_at     DATETIME     NULL COMMENT 'JWT exp 解析后过期时间（UTC naive）';
