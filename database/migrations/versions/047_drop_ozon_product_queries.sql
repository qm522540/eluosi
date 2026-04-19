-- Migration: 047_drop_ozon_product_queries.sql
-- Author: 老林
-- Date: 2026-04-19
-- Description:
--   合并清理：废弃 ozon_product_queries 表
--   原由 045 创建，现合并到 product_search_queries（platform='ozon'），与老张
--   搜索词洞察共用底表，避免双倍 Premium 配额消耗。
--   生产部署时机：确认 ozon_product_queries_task 已切到新表写入后再跑此迁移。
--   安全前提：表当前 0 行（合并前已确认），无数据丢失风险。

SET NAMES utf8mb4;

DROP TABLE IF EXISTS `ozon_product_queries`;
