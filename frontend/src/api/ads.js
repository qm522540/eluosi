import request from './index'

/** 广告活动列表 */
export function getCampaigns(params) {
  return request.get('/ads/campaigns', { params })
}

/** 广告活动详情 */
export function getCampaign(id) {
  return request.get(`/ads/campaigns/${id}`)
}

/** 更新广告活动（预算/状态） */
export function updateCampaign(id, data) {
  return request.put(`/ads/campaigns/${id}`, data)
}

/** 广告统计数据（按天+平台） */
export function getAdStats(params) {
  return request.get('/ads/stats', { params })
}

/** 广告汇总数据 */
export function getAdSummary(params) {
  return request.get('/ads/summary', { params })
}
