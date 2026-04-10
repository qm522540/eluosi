import request from './index'

/** 触发WB AI分析 */
export function triggerWBAnalysis(shopId) {
  return request.post(`/ai-pricing/wb/analyze/${shopId}`)
}

/** 获取WB待确认建议（含后台直链） */
export function getWBSuggestions(shopId, params = {}) {
  return request.get(`/ai-pricing/wb/suggestions/${shopId}`, { params })
}

/** 拒绝WB建议 */
export function rejectWBSuggestion(suggestionId) {
  return request.post(`/ai-pricing/wb/suggestions/${suggestionId}/reject`)
}
