import request from './index'

const BASE = '/reviews'

/** 评价分页列表 — 按店铺 + 多过滤 */
export function listReviews(shopId, params = {}) {
  return request.get(BASE, { params: { shop_id: shopId, ...params } })
}

/** 红点角标计数 — shopId=null 即本租户全店聚合 */
export function getUnreadCount(shopId = null) {
  const params = shopId ? { shop_id: shopId } : {}
  return request.get(`${BASE}/unread-count`, { params })
}

/** 手动触发拉取 (单店, 走 review provider 拉新评价) */
export function syncReviews(shopId, body = {}) {
  return request.post(`${BASE}/${shopId}/sync`, body, { timeout: 120000 })
}

/** 标已读 (业务层 unread→read) */
export function markReviewRead(reviewId) {
  return request.patch(`${BASE}/${reviewId}/mark-read`)
}

/** 轻量翻译 — 用户编辑俄语后刷新中文 (不调 AI 生成, 复用 ru_zh_dict 缓存) */
export function translateText(textRu) {
  return request.post(`${BASE}/translate`, { text_ru: textRu },
    { timeout: 30000 })
}

/** AI 生成俄语回复草稿 + 中文翻译; 重生成传新 custom_hint */
export function generateReply(reviewId, customHint = '') {
  return request.post(`${BASE}/${reviewId}/generate-reply`,
    { custom_hint: customHint }, { timeout: 60000 })
}

/** 真实发送回复到平台. final_content_ru 为用户编辑后版本; null=用 draft 原版 */
export function sendReply(reviewId, replyId, finalContentRu = null) {
  return request.post(`${BASE}/${reviewId}/send-reply`,
    { reply_id: replyId, final_content_ru: finalContentRu },
    { timeout: 30000 })
}

/** 取店铺评价配置 */
export function getReviewSettings(shopId) {
  return request.get(`${BASE}/settings/${shopId}`)
}

/** 改店铺评价配置 (auto_reply 开关 / 语气 / 签名 / 自定义 prompt) */
export function updateReviewSettings(shopId, body) {
  return request.patch(`${BASE}/settings/${shopId}`, body)
}
