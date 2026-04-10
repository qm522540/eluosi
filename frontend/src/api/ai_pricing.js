import request from './index'

/** 获取店铺调价配置列表 */
export function getConfigs(shopId) {
  return request.get(`/ai-pricing/configs/${shopId}`)
}

/** 更新调价配置 */
export function updateConfig(configId, data) {
  return request.put(`/ai-pricing/configs/${configId}`, data)
}

/** 手动触发AI分析 */
export function analyzeShop(shopId, data = {}) {
  return request.post(`/ai-pricing/analyze/${shopId}`, data)
}

/** 获取建议列表 */
export function getSuggestions(shopId, params) {
  return request.get(`/ai-pricing/suggestions/${shopId}`, { params })
}

/** 确认执行建议 */
export function approveSuggestion(suggestionId) {
  return request.post(`/ai-pricing/suggestions/${suggestionId}/approve`)
}

/** 拒绝建议 */
export function rejectSuggestion(suggestionId) {
  return request.post(`/ai-pricing/suggestions/${suggestionId}/reject`)
}

/** 切换自动/建议模式 */
export function toggleAutoExecute(shopId, data) {
  return request.post(`/ai-pricing/toggle-auto/${shopId}`, data)
}

/** 调价历史记录 */
export function getHistory(shopId, params) {
  return request.get(`/ai-pricing/history/${shopId}`, { params })
}

/** 获取当前大促状态 */
export function getPromoStatus(tenantId) {
  return request.get(`/ai-pricing/promo-status/${tenantId}`)
}

/** 获取大促日历列表 */
export function getPromoCalendars(tenantId) {
  return request.get(`/ai-pricing/promo-calendars/${tenantId}`)
}

/** 新增大促节点 */
export function createPromoCalendar(data) {
  return request.post('/ai-pricing/promo-calendars', data)
}

/** 检查店铺数据初始化状态 */
export function getDataStatus(shopId) {
  return request.get(`/ai-pricing/data-status/${shopId}`)
}
