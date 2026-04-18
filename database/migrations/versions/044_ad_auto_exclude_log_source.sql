-- Migration: 044_ad_auto_exclude_log_source.sql
-- Author: 老林
-- Date: 2026-04-18
-- Description:
--   ad_auto_exclude_log 加 source 字段，区分自动 vs 用户手动「一键屏蔽」
--   配合统一账本：所有屏蔽行为（auto / manual）都进同一张表，
--   全店成果汇总按 source 分别累计 + 总和。

SET NAMES utf8mb4;

ALTER TABLE `ad_auto_exclude_log`
  ADD COLUMN `source` VARCHAR(10) NOT NULL DEFAULT 'auto'
    COMMENT 'auto=定时/立即跑, manual=用户一键屏蔽'
  AFTER `reason`;

-- 历史数据全部归类为 auto（之前只有 auto 写入路径）
UPDATE `ad_auto_exclude_log` SET `source` = 'auto' WHERE `source` IS NULL OR `source` = '';
