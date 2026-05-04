-- 068_review_replies_unique_sent.sql
-- 2026-05-04 老张 — 评价回复加 DB 层唯一约束防重发 (老林 review 建议 #2)
--
-- 问题: 同一 review 理论上能发多条 reply (草稿多版本 OK), 但 sent_status='sent' 应该只能 1 条.
-- 应用层只检查 (sent, pending), race condition (用户狂点 + Celery auto_reply 同时跑) 仍可能漏.
-- DB 层兜底: generated column 把 (sent + review_id) 算成唯一 key, sent_status='sent' 时强制唯一,
--           其他状态时为 NULL (NULL 不参与 UNIQUE 校验, 不影响草稿多版本).
--
-- 关联文档: docs/daily/2026-05-04_review_老林给老张_评价模块.md (建议 #2)
-- 关联代码: app/services/reviews/service.py send_reply 已加 (sent, pending) 软检查 (BUG B 修)

ALTER TABLE shop_review_replies
  ADD COLUMN sent_lock_key VARCHAR(80)
    GENERATED ALWAYS AS (
        IF(sent_status = 'sent', CONCAT('sent-', review_id), NULL)
    ) STORED
    COMMENT 'Generated 兜底键: sent 时 = "sent-{review_id}" 用于唯一约束, 其他状态 NULL',
  ADD UNIQUE KEY uk_one_sent_per_review (sent_lock_key);
