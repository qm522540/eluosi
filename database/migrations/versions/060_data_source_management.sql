-- 060_data_source_management.sql
-- 数据源管理 Tab — DB Schema
--
-- 目的: 把 WB 静默期的"硬注释 MANUAL HOLD"换成 DB 驱动的运行时开关,
--       让用户在 UI 一键启停任意 (店铺 × 数据源) 组合,quota 事故时秒级止血。
--
-- 两层权限:
-- - Level 1 (店铺级): shops.api_enabled — 关 = 该店所有 API 类数据源全部 skip
-- - Level 2 (数据源级): data_source_config.enabled — 单源精细控制
--
-- 规则 1 多租户: data_source_config 三列 (tenant_id, shop_id, source_key) 唯一
-- 规则 6 时间: 默认值用 CURRENT_TIMESTAMP 仅占位,运行时业务字段必须显式传 utc_now_naive()

-- ==================== 1. shops 加店铺级 API 总开关字段 ====================

ALTER TABLE shops
    ADD COLUMN api_enabled TINYINT(1) NOT NULL DEFAULT 1
        COMMENT '店铺 API 总开关 1=允许 0=禁用,关闭时该店所有 API 类数据源全部 skip',
    ADD COLUMN api_disabled_reason VARCHAR(500) DEFAULT NULL
        COMMENT '禁用原因,展示给所有人看 (如 "WB quota 静默期")',
    ADD COLUMN api_disabled_at DATETIME DEFAULT NULL
        COMMENT '禁用时间 (UTC naive)',
    ADD COLUMN api_disabled_until DATETIME DEFAULT NULL
        COMMENT '自动恢复时间 (UTC naive),NULL=手动启用前一直禁用',
    ADD COLUMN api_disabled_by BIGINT DEFAULT NULL
        COMMENT '禁用操作人 user_id (审计用)';

-- ==================== 2. data_source_config 表 ====================

CREATE TABLE IF NOT EXISTS data_source_config (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    tenant_id BIGINT NOT NULL,
    shop_id BIGINT NOT NULL,
    source_key VARCHAR(64) NOT NULL
        COMMENT '数据源标识,跟 catalog.py DATA_SOURCES 对齐 (如 wb_orders, ozon_search_texts)',

    -- 开关
    enabled TINYINT(1) NOT NULL DEFAULT 1
        COMMENT '该数据源开关 1=启用 0=暂停 (Level 2 精细控制)',
    manual_hold_reason VARCHAR(500) DEFAULT NULL
        COMMENT '暂停原因 (如 "WB quota 静默" / "WB 后台账号被冻")',
    disabled_at DATETIME DEFAULT NULL
        COMMENT '暂停时间',
    disabled_by BIGINT DEFAULT NULL
        COMMENT '暂停操作人',

    -- 运行状态 (供 UI 展示用,beat hook 写回)
    last_sync_at DATETIME DEFAULT NULL
        COMMENT '最近一次 task 实际执行时间',
    last_sync_status VARCHAR(20) DEFAULT NULL
        COMMENT 'success / partial / failed / skipped',
    last_sync_msg VARCHAR(500) DEFAULT NULL
        COMMENT '最近一次执行的简短消息 / 错误摘要',
    last_sync_rows INT NOT NULL DEFAULT 0
        COMMENT '最近一次写入行数',
    last_sync_duration_ms INT DEFAULT NULL
        COMMENT '最近一次耗时 ms',

    -- 时间戳
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_tenant_shop_source (tenant_id, shop_id, source_key),
    KEY idx_enabled_source (enabled, source_key),
    KEY idx_shop_status (shop_id, last_sync_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='数据源开关 + 同步状态 (店铺×数据源粒度)';
