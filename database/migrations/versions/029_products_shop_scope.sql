-- Migration: 029_products_shop_scope.sql
-- Author: 老张
-- Date: 2026-04-16
-- Description:
--   products 从"租户级 SKU 共享"改为"店铺级 SKU 独立"
--   原因：同一 SKU 在不同平台/店铺的净毛利率、成本、售价都可能不同
--   做法：
--     1) products 加 shop_id 字段
--     2) 唯一键从 (tenant_id, sku) 改为 (tenant_id, shop_id, sku)
--     3) 历史数据按 platform_listings.shop_id 拆分：
--        - 原来一个 product 被多个 shop 的 listing 引用的情况，
--          给除第一个外的每个 shop 各复制一份 product，
--          更新对应 listing.product_id 指向新 product

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- Step 1: products 加 shop_id 字段（幂等，列存在则跳过）
SET @has_col := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'products'
      AND COLUMN_NAME = 'shop_id'
);
SET @add_col_sql := IF(@has_col = 0,
    "ALTER TABLE `products` ADD COLUMN `shop_id` BIGINT UNSIGNED DEFAULT NULL COMMENT '所属店铺ID（同一SKU在不同店铺独立记录）' AFTER `tenant_id`",
    'SELECT 1');
PREPARE s1 FROM @add_col_sql; EXECUTE s1; DEALLOCATE PREPARE s1;

-- Step 1a: 加辅助索引（幂等）
SET @has_idx := (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'products'
      AND INDEX_NAME = 'idx_tenant_shop_sku'
);
SET @add_idx_sql := IF(@has_idx = 0,
    'ALTER TABLE `products` ADD INDEX `idx_tenant_shop_sku` (`tenant_id`, `shop_id`, `sku`)',
    'SELECT 1');
PREPARE s2 FROM @add_idx_sql; EXECUTE s2; DEALLOCATE PREPARE s2;

-- Step 1b: 删除旧唯一键 (tenant_id, sku) —— 它阻止同一 SKU 跨店铺复制
SET @has_old_uk := (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'products'
      AND INDEX_NAME = 'uk_products_tenant_sku'
);
SET @drop_sql := IF(@has_old_uk > 0,
    'ALTER TABLE `products` DROP INDEX `uk_products_tenant_sku`',
    'SELECT 1');
PREPARE s3 FROM @drop_sql; EXECUTE s3; DEALLOCATE PREPARE s3;

-- Step 2: 数据迁移：按 listing.shop_id 拆分共用的 product
--
-- 策略：
--   1) 先把 product.shop_id 置为其第一个 listing 的 shop_id（保留原 product_id）
--   2) 对于"一个 product 被多个 shop 引用"的场景：
--      - 第一个 shop 继续用原 product（shop_id 已填）
--      - 其余 shop 各复制一份新的 product，listing.product_id 改指向新的

-- 2a. 用 listing 里第一个 shop_id 回填 product.shop_id
UPDATE products p
JOIN (
    SELECT product_id, MIN(shop_id) AS first_shop_id
    FROM platform_listings
    WHERE status != 'deleted'
    GROUP BY product_id
) t ON t.product_id = p.id
SET p.shop_id = t.first_shop_id
WHERE p.shop_id IS NULL;

-- 2b. 找出"一个 product 被多个 shop 引用"的情况，给每个额外 shop 复制一份 product
--    用存储过程拆分
DROP PROCEDURE IF EXISTS split_products_by_shop;
DELIMITER $$
CREATE PROCEDURE split_products_by_shop()
BEGIN
    DECLARE done INT DEFAULT 0;
    DECLARE v_product_id BIGINT;
    DECLARE v_shop_id BIGINT;
    DECLARE v_new_product_id BIGINT;

    DECLARE cur CURSOR FOR
        SELECT pl.product_id, pl.shop_id
        FROM platform_listings pl
        JOIN products p ON p.id = pl.product_id
        WHERE pl.status != 'deleted'
          AND pl.shop_id != p.shop_id;  -- listing 的 shop_id 和 product.shop_id 不一致

    DECLARE CONTINUE HANDLER FOR NOT FOUND SET done = 1;

    OPEN cur;
    read_loop: LOOP
        FETCH cur INTO v_product_id, v_shop_id;
        IF done THEN LEAVE read_loop; END IF;

        -- 复制一份 product，shop_id 改为当前 listing 的 shop_id
        INSERT INTO products (
            tenant_id, shop_id, sku, name_zh, name_ru, brand, category,
            local_category_id, cost_price, net_margin, weight_g, image_url,
            status, created_at, updated_at
        )
        SELECT
            tenant_id, v_shop_id, sku, name_zh, name_ru, brand, category,
            local_category_id, cost_price, net_margin, weight_g, image_url,
            status, NOW(), NOW()
        FROM products WHERE id = v_product_id;

        SET v_new_product_id = LAST_INSERT_ID();

        -- 把这个 shop 下的 listing 重定向到新 product
        UPDATE platform_listings
        SET product_id = v_new_product_id
        WHERE product_id = v_product_id
          AND shop_id = v_shop_id
          AND status != 'deleted';
    END LOOP;
    CLOSE cur;
END$$
DELIMITER ;

CALL split_products_by_shop();
DROP PROCEDURE split_products_by_shop;

-- Step 3: 置 shop_id 为非空（MODIFY 幂等）
ALTER TABLE `products`
    MODIFY COLUMN `shop_id` BIGINT UNSIGNED NOT NULL
        COMMENT '所属店铺ID（同一SKU在不同店铺独立记录）';

-- Step 3a: 新增唯一键 uk_tenant_shop_sku（幂等）
SET @has_new_uk := (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'products'
      AND INDEX_NAME = 'uk_tenant_shop_sku'
);
SET @add_new_uk := IF(@has_new_uk = 0,
    'ALTER TABLE `products` ADD UNIQUE KEY `uk_tenant_shop_sku` (`tenant_id`, `shop_id`, `sku`)',
    'SELECT 1');
PREPARE s4 FROM @add_new_uk; EXECUTE s4; DEALLOCATE PREPARE s4;

-- Step 3b: 删除辅助普通索引（唯一键已覆盖查询，幂等）
SET @has_aux_idx := (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'products'
      AND INDEX_NAME = 'idx_tenant_shop_sku'
);
SET @drop_aux := IF(@has_aux_idx > 0,
    'ALTER TABLE `products` DROP INDEX `idx_tenant_shop_sku`',
    'SELECT 1');
PREPARE s5 FROM @drop_aux; EXECUTE s5; DEALLOCATE PREPARE s5;

SET FOREIGN_KEY_CHECKS = 1;
