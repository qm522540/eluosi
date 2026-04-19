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

/** 手动执行规则（传shopId时只执行该店铺的启用规则） */
export function executeRules(shopId) {
  const params = shopId ? { shop_id: shopId } : undefined
  return request.post('/ads/rules/execute', null, { params })
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
/** 获取 WB 活动关键词统计 + 屏蔽词（传 nm_id 拿该 SKU 的屏蔽列表） */
export function getCampaignKeywords(campaignId, days = 7, nmId = null) {
  const params = { days }
  if (nmId) params.nm_id = nmId
  // WB 关键词接口可能因限速重试 ≥15s，放宽前端 timeout 到 60s
  return request.get(`/ads/campaign-keywords/${campaignId}`, { params, timeout: 60000 })
}

/** 屏蔽关键词：把指定词加入 WB minus-phrases */
export function excludeKeywords(campaignId, nmId, keywords) {
  return request.post(`/ads/campaign-keywords/${campaignId}/exclude`, {
    nm_id: nmId,
    keywords,
  })
}

/** 加入智能屏蔽白名单（被勾入后即使是浪费词也不会被一键屏蔽） */
export function addProtectedKeyword(campaignId, nmId, keyword) {
  return request.post(`/ads/campaign-keywords/${campaignId}/protected`, {
    nm_id: nmId, keyword,
  })
}

/** 从智能屏蔽白名单移除 */
export function removeProtectedKeyword(campaignId, nmId, keyword) {
  return request.delete(`/ads/campaign-keywords/${campaignId}/protected`, {
    data: { nm_id: nmId, keyword },
  })
}

// ==================== Ozon SKU × 搜索词 ====================

export function getOzonSkuQueries(shopId, sku, days = 7) {
  return request.get('/ads/ozon-sku-queries', { params: { shop_id: shopId, sku, days } })
}

export function syncOzonSkuQueries(shopId, days = 7) {
  return request.post('/ads/ozon-sku-queries/sync', null, { params: { shop_id: shopId, days } })
}

// ==================== 活动汇总指标 ====================

export function getCampaignSummary(campaignId, days = 7) {
  // WB fullstats 在限速时后端会重试 ≥15s，放宽前端 timeout 到 60s
  return request.get(`/ads/campaign-summary/${campaignId}`, { params: { days }, timeout: 60000 })
}

// ==================== 活动级自动屏蔽托管 ====================

export function getAutoExcludeConfig(campaignId) {
  return request.get(`/ads/campaign-auto-exclude/${campaignId}`)
}

export function toggleAutoExclude(campaignId, enabled) {
  return request.put(`/ads/campaign-auto-exclude/${campaignId}`, { enabled })
}

export function runAutoExcludeNow(campaignId) {
  return request.post(`/ads/campaign-auto-exclude/${campaignId}/run`, {}, { timeout: 120000 })
}

export function getAutoExcludeLogs(campaignId, days = 30) {
  return request.get(`/ads/campaign-auto-exclude/${campaignId}/logs`, { params: { days } })
}

export function getAutoExcludeSummary(shopId, days = 30) {
  return request.get(`/ads/auto-exclude/summary`, { params: { shop_id: shopId, days } })
}

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

/** 获取店铺调价配置列表（3 档模板虚拟数组） */
export function getAIPricingConfigs(shopId) {
  return request.get(`/bid-management/ai-pricing/configs/${shopId}`)
}

/** 更新单档模板配置（payload 必须带 template_type） */
export function updateAIPricingConfig(shopId, data) {
  return request.put(`/bid-management/ai-pricing/configs/${shopId}`, data)
}

/** 手动触发AI分析 */
export function triggerAIAnalysis(shopId, data = {}) {
  return request.post(`/bid-management/ai-pricing/${shopId}/analyze`, data, { timeout: 120000 })
}

/** 获取AI调价建议列表 */
export function getAIPricingSuggestions(shopId, params) {
  return request.get(`/bid-management/suggestions/${shopId}`, { params })
}

/** 确认执行AI调价建议 */
export function approveAIPricingSuggestion(suggestionId) {
  return request.post(`/bid-management/suggestions/${suggestionId}/approve`)
}

/** 拒绝AI调价建议 */
export function rejectAIPricingSuggestion(suggestionId) {
  return request.post(`/bid-management/suggestions/${suggestionId}/reject`)
}

/** 忽略建议：该SKU长期不参与自动调价/删除 */
export function ignoreAIPricingSuggestion(suggestionId) {
  return request.post(`/bid-management/suggestions/${suggestionId}/ignore`)
}

/** 恢复：该SKU重新参与自动调价 */
export function restoreAIPricingSuggestion(suggestionId) {
  return request.post(`/bid-management/suggestions/${suggestionId}/restore`)
}

/** 切换AI调价自动/建议模式（复用 PUT 配置接口更新 auto_execute） */
export function toggleAIAutoExecute(shopId, data) {
  return request.put(`/bid-management/ai-pricing/configs/${shopId}`, {
    template_type: 'default',
    auto_execute: !!data.auto_execute,
  })
}

/** 获取AI调价历史记录（出价日志）
 *  默认 execute_type='all' → 返回所有出价调整记录（ai_auto/ai_manual/auto_remove/user_manual/time_pricing...）
 *  调用方可显式传 execute_type 做过滤
 */
export function getAIPricingHistory(shopId, params) {
  return request.get(`/bid-management/bid-logs/${shopId}`, { params })
}

/** 获取所有策略模板列表 */
export function getAIPricingTemplates() {
  return request.get('/ai-pricing/templates')
}

/** 更新广告活动的调价配置（绑定模板/覆盖参数） */
export function updateCampaignPricingConfig(campaignId, data) {
  return request.put(`/ai-pricing/campaigns/${campaignId}/config`, data)
}

/** 活动级当日实时汇总（今日花费/订单/曝光/点击/ROAS + 预算余额） */
export function getTodaySummaryByCampaign(campaignId, refresh = false) {
  return request.get(`/ads/today-summary/campaign/${campaignId}`, {
    params: refresh ? { refresh: true } : {},
  })
}

/** 店铺级当日实时汇总（聚合店铺下所有 active 活动） */
export function getTodaySummaryByShop(shopId, refresh = false) {
  return request.get(`/ads/today-summary/shop/${shopId}`, {
    params: refresh ? { refresh: true } : {},
  })
}

/** 店铺级当日异常告警（烧钱无单 / ROAS<1 / 预算低） */
export function getTodayAlertsByShop(shopId) {
  return request.get(`/ads/today-alerts/shop/${shopId}`)
}
