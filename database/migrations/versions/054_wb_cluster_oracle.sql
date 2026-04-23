-- 054: WB 顶级搜索集群 oracle 表（用户导出 preset-stat xlsx 上传）
--
-- 背景：2026-04-23 分析用户导出的 preset-stat-{adv}-{nm}_{from}-{to}.xlsx
-- 发现 WB 后台"顶级搜索集群"与 /adv/v0/stats/keywords API 是两个数据源：
--   - /adv/v0/stats/keywords：近期真实产生展示/点击的活跃触发词（~175 个）
--   - WB seller-analytics 顶级集群：含长尾归类推断词（~253 个去重）
--   两边交集仅 6 个词（2.4% 覆盖率）。
--
-- xlsx 包含完整 253 词 × 6 簇权威映射（WB 官方判定，100% 准确）。
-- 通过"用户手动上传 xlsx"建立 oracle，聚类 API 优先查 oracle 命中直接返；
-- 未命中才降级到 DeepSeek AI 三步聚类。
--
-- 两张表：
--   wb_cluster_oracle          关键词 → 集群的映射（每条 xlsx 导入一批）
--   wb_cluster_oracle_summary  每个集群的汇总统计（展示/点击/订单/花费 等）

CREATE TABLE IF NOT EXISTS wb_cluster_oracle (
    id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    tenant_id    BIGINT UNSIGNED NOT NULL,
    shop_id      BIGINT UNSIGNED NOT NULL,
    advert_id    BIGINT UNSIGNED NOT NULL COMMENT 'WB platform_campaign_id',
    nm_id        BIGINT UNSIGNED NOT NULL COMMENT 'WB SKU nm_id',
    cluster_name VARCHAR(500) NOT NULL COMMENT 'WB 官方簇代表词',
    keyword      VARCHAR(500) NOT NULL COMMENT '归入该簇的用户搜索词',
    date_from    DATE NULL,
    date_to      DATE NULL,
    imported_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_file  VARCHAR(300) NULL COMMENT '上传文件名',
    UNIQUE KEY uk_oracle_kw (tenant_id, advert_id, nm_id, keyword),
    KEY idx_oracle_advert_nm (advert_id, nm_id),
    KEY idx_oracle_tenant_shop (tenant_id, shop_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='WB 顶级搜索集群 keyword→cluster 映射 oracle';

CREATE TABLE IF NOT EXISTS wb_cluster_oracle_summary (
    id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    tenant_id    BIGINT UNSIGNED NOT NULL,
    shop_id      BIGINT UNSIGNED NOT NULL,
    advert_id    BIGINT UNSIGNED NOT NULL,
    nm_id        BIGINT UNSIGNED NOT NULL,
    cluster_name VARCHAR(500) NOT NULL,
    status_type  VARCHAR(100) NULL COMMENT 'xlsx "Статус и тип ставки"，Активная/Исключение 等',
    is_excluded  TINYINT(1) NOT NULL DEFAULT 0 COMMENT '该簇是否被屏蔽（灰色）',
    bid_cpm      DECIMAL(10,2) NULL COMMENT '该簇 CPM 出价',
    avg_pos      DECIMAL(10,2) NULL,
    views        INT UNSIGNED NOT NULL DEFAULT 0,
    clicks       INT UNSIGNED NOT NULL DEFAULT 0,
    ctr          DECIMAL(6,2) NULL,
    baskets      INT UNSIGNED NOT NULL DEFAULT 0,
    orders       INT UNSIGNED NOT NULL DEFAULT 0,
    ordered_items INT UNSIGNED NOT NULL DEFAULT 0,
    spend        DECIMAL(10,2) NOT NULL DEFAULT 0,
    cpm          DECIMAL(10,2) NULL,
    cpc          DECIMAL(10,2) NULL,
    currency     VARCHAR(10) NULL DEFAULT 'RUB',
    date_from    DATE NULL,
    date_to      DATE NULL,
    imported_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_file  VARCHAR(300) NULL,
    UNIQUE KEY uk_summary (tenant_id, advert_id, nm_id, cluster_name, date_from, date_to),
    KEY idx_summary_advert_nm (advert_id, nm_id),
    KEY idx_summary_tenant_shop (tenant_id, shop_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='WB 顶级搜索集群汇总统计';
