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

/** 店铺今日汇总（概览卡片） */
export function getShopSummary(shopId) {
  return request.get(`/ads/shop-summary/${shopId}`)
}

/** 手动触发广告数据同步 */
export function syncAds() {
  return request.post('/tasks/sync-ads')
}

/** 手动触发指定平台广告数据同步 */
export function syncAdsByPlatform(platform) {
  return request.post(`/tasks/sync-ads/${platform}`)
}

/** 获取店铺上次同步时间（通过店铺详情） */
export function getLastSyncTime(shopId) {
  return request.get(`/shops/${shopId}`)
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

// ==================== 数据分析 ====================

/** 多平台对比分析 */
export function getPlatformComparison(params) {
  return request.get('/ads/analysis/platform-comparison', { params })
}

/** 广告活动TOP排名 */
export function getCampaignRanking(params) {
  return request.get('/ads/analysis/campaign-ranking', { params })
}

/** 商品级ROI分析 */
export function getProductRoi(params) {
  return request.get('/ads/analysis/product-roi', { params })
}

// ==================== 自动化规则 ====================

/** 获取自动化规则列表 */
export function getAutomationRules(params) {
  return request.get('/ads/rules', { params })
}

/** 创建自动化规则 */
export function createAutomationRule(data) {
  return request.post('/ads/rules', data)
}

/** 更新自动化规则 */
export function updateAutomationRule(id, data) {
  return request.put(`/ads/rules/${id}`, data)
}

/** 删除自动化规则 */
export function deleteAutomationRule(id) {
  return request.delete(`/ads/rules/${id}`)
}

/** 恢复规则原始出价 */
export function restoreRuleBids(id) {
  return request.post(`/ads/rules/${id}/restore-bids`)
}

/** 手动执行规则 */
export function executeRules() {
  return request.post('/ads/rules/execute')
}

// ==================== 预算管理 ====================

/** 预算消耗概览 */
export function getBudgetOverview(params) {
  return request.get('/ads/budget/overview', { params })
}

/** 预算分配优化建议 */
export function getBudgetSuggestions(params) {
  return request.get('/ads/budget/suggestions', { params })
}

// ==================== 活动详情增强 ====================

/** 获取活动关联商品及出价 */
export function getCampaignProducts(campaignId) {
  return request.get(`/ads/campaign-products/${campaignId}`)
}

/** 修改商品出价 */
export function updateCampaignBid(campaignId, data) {
  return request.post(`/ads/campaign-products/${campaignId}/update-bid`, data)
}

/** 获取活动预算余额（实时） */
export function getCampaignBudget(campaignId) {
  return request.get(`/ads/campaign-budget/${campaignId}`)
}

/** 获取出价调整日志 */
export function getBidLogs(params) {
  return request.get('/ads/bid-logs', { params })
}

// ==================== AI智能调价 ====================

/** 获取店铺调价配置列表 */
export function getAIPricingConfigs(shopId) {
  return request.get(`/ai-pricing/configs/${shopId}`)
}

/** 更新调价配置 */
export function updateAIPricingConfig(configId, data) {
  return request.put(`/ai-pricing/configs/${configId}`, data)
}

/** 手动触发AI分析 */
export function triggerAIAnalysis(shopId, data = {}) {
  return request.post(`/ai-pricing/analyze/${shopId}`, data)
}

/** 获取AI调价建议列表 */
export function getAIPricingSuggestions(shopId, params) {
  return request.get(`/ai-pricing/suggestions/${shopId}`, { params })
}

/** 确认执行AI调价建议 */
export function approveAIPricingSuggestion(suggestionId) {
  return request.post(`/ai-pricing/suggestions/${suggestionId}/approve`)
}

/** 拒绝AI调价建议 */
export function rejectAIPricingSuggestion(suggestionId) {
  return request.post(`/ai-pricing/suggestions/${suggestionId}/reject`)
}

/** 切换AI调价自动/建议模式 */
export function toggleAIAutoExecute(shopId, data) {
  return request.post(`/ai-pricing/toggle-auto/${shopId}`, data)
}

/** 获取AI调价历史记录 */
export function getAIPricingHistory(shopId, params) {
  return request.get(`/ai-pricing/history/${shopId}`, { params })
}

/** 获取所有策略模板列表 */
export function getAIPricingTemplates() {
  return request.get('/ai-pricing/templates')
}

/** 更新广告活动的调价配置（绑定模板/覆盖参数） */
export function updateCampaignPricingConfig(campaignId, data) {
  return request.put(`/ai-pricing/campaigns/${campaignId}/config`, data)
}
