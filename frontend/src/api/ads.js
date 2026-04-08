import request from './index'

/** 广告活动列表 */
export function getCampaigns(params) {
  return request.get('/ads/campaigns', { params })
}

/** 广告活动详情 */
export function getCampaign(id) {
  return request.get(`/ads/campaigns/${id}`)
}

/** 创建广告活动 */
export function createCampaign(data) {
  return request.post('/ads/campaigns', data)
}

/** 更新广告活动（预算/状态） */
export function updateCampaign(id, data) {
  return request.put(`/ads/campaigns/${id}`, data)
}

/** 删除广告活动 */
export function deleteCampaign(id) {
  return request.delete(`/ads/campaigns/${id}`)
}

/** 广告组列表 */
export function getAdGroups(params) {
  return request.get('/ads/groups', { params })
}

/** 创建广告组 */
export function createAdGroup(data) {
  return request.post('/ads/groups', data)
}

/** 更新广告组 */
export function updateAdGroup(id, data) {
  return request.put(`/ads/groups/${id}`, data)
}

/** 删除广告组 */
export function deleteAdGroup(id) {
  return request.delete(`/ads/groups/${id}`)
}

/** 关键词列表 */
export function getKeywords(params) {
  return request.get('/ads/keywords', { params })
}

/** 创建关键词 */
export function createKeyword(data) {
  return request.post('/ads/keywords', data)
}

/** 批量创建关键词 */
export function batchCreateKeywords(data) {
  return request.post('/ads/keywords/batch', data)
}

/** 更新关键词 */
export function updateKeyword(id, data) {
  return request.put(`/ads/keywords/${id}`, data)
}

/** 删除关键词 */
export function deleteKeyword(id) {
  return request.delete(`/ads/keywords/${id}`)
}

/** 广告统计数据（按天+平台） */
export function getAdStats(params) {
  return request.get('/ads/stats', { params })
}

/** 广告汇总数据 */
export function getAdSummary(params) {
  return request.get('/ads/summary', { params })
}

/** 手动触发广告数据同步 */
export function syncAds() {
  return request.post('/tasks/sync-ads')
}

/** 出价优化建议 */
export function getOptimizeSuggestions(data) {
  return request.post('/ads/optimize', data)
}

/** 应用出价建议 */
export function applyBidSuggestions(suggestions) {
  return request.post('/ads/optimize/apply', suggestions)
}

/** 导出广告统计CSV */
export function exportAdStats(params) {
  return request.get('/ads/export', { params, responseType: 'blob' })
}

/** ROI告警列表 */
export function getAlerts(params) {
  return request.get('/ads/alerts', { params })
}

/** 获取告警阈值配置 */
export function getAlertConfig() {
  return request.get('/ads/alert-config')
}

/** 更新告警阈值配置 */
export function updateAlertConfig(data) {
  return request.put('/ads/alert-config', data)
}
