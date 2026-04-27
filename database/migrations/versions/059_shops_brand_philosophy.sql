-- Migration: 059_shops_brand_philosophy.sql
-- Author: 老张
-- Date: 2026-04-27
-- Description:
--   shops 表加 brand_philosophy 字段, 用于 AI 描述生成时拼入 prompt。
--   店铺级配置, 同店所有商品共享。AiDescriptionModal 弹窗里编辑/清空。
--   500 字符上限, NULL 表示不传给 AI。

ALTER TABLE `shops`
ADD COLUMN `brand_philosophy` VARCHAR(500) NULL DEFAULT NULL
COMMENT '店铺品牌理念,AI 描述生成时拼入 prompt;NULL=不传'
AFTER `name`;
