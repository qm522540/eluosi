import request from './index'

const BASE = '/bid-management'

// ==================== 状态栏 ====================
export const getDashboard = (shopId) =>
  request.get(`${BASE}/dashboard/${shopId}`)

// ==================== 分时调价 ====================
export const getTimePricing = (shopId) =>
  request.get(`${BASE}/time-pricing/${shopId}`)

export const updateTimePricing = (shopId, data) =>
  request.put(`${BASE}/time-pricing/${shopId}`, data)

export const enableTimePricing = (shopId) =>
  request.post(`${BASE}/time-pricing/${shopId}/enable`)

export const disableTimePricing = (shopId) =>
  request.post(`${BASE}/time-pricing/${shopId}/disable`)

export const restoreSku = (shopId, skuId) =>
  request.post(`${BASE}/time-pricing/${shopId}/restore-sku`, {
    platform_sku_id: skuId,
  })

export const getTimePricingStatus = (shopId) =>
  request.get(`${BASE}/time-pricing/${shopId}/status`)

// ==================== AI调价 ====================
export const getAIPricing = (shopId) =>
  request.get(`${BASE}/ai-pricing/${shopId}`)

export const updateAIPricing = (shopId, data) =>
  request.put(`${BASE}/ai-pricing/${shopId}`, data)

export const enableAIPricing = (shopId, autoExecute) =>
  request.post(`${BASE}/ai-pricing/${shopId}/enable`, {
    auto_execute: autoExecute,
  })

export const disableAIPricing = (shopId) =>
  request.post(`${BASE}/ai-pricing/${shopId}/disable`)

export const manualAnalyze = (shopId) =>
  request.post(`${BASE}/ai-pricing/${shopId}/analyze`)

// ==================== 建议列表 ====================
export const getSuggestions = (shopId) =>
  request.get(`${BASE}/suggestions/${shopId}`)

export const approveSuggestion = (id) =>
  request.post(`${BASE}/suggestions/${id}/approve`)

export const rejectSuggestion = (id) =>
  request.post(`${BASE}/suggestions/${id}/reject`)

export const approveBatch = (ids) =>
  request.post(`${BASE}/suggestions/approve-batch`, { ids })

export const rejectBatch = (ids) =>
  request.post(`${BASE}/suggestions/reject-batch`, { ids })

// ==================== 冲突检测 ====================
export const checkConflict = (shopId, enabling) =>
  request.get(`${BASE}/conflict-check/${shopId}`, {
    params: { enabling },
  })

// ==================== 调价历史 ====================
export const getBidLogs = (shopId, params) =>
  request.get(`${BASE}/bid-logs/${shopId}`, { params })

// ==================== 数据源 ====================
export const getDataStatus = (shopId) =>
  request.get(`${BASE}/data-status/${shopId}`)

export const syncData = (shopId) =>
  request.post(`${BASE}/data-sync/${shopId}`, null, { timeout: 300000 })

export const downloadData = (shopId, days) =>
  request.get(`${BASE}/data-download/${shopId}`, {
    params: { days },
    responseType: 'blob',
  })
