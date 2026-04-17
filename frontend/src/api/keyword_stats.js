import request from './index'

const BASE = '/keyword-stats'

export function getKeywordSummary(params) {
  return request.get(`${BASE}/summary`, { params })
}

export function getKeywordSkuDetail(params) {
  return request.get(`${BASE}/sku-detail`, { params })
}

export function getKeywordTrend(params) {
  return request.get(`${BASE}/trend`, { params })
}

export function backfillKeywords(data) {
  return request.post(`${BASE}/backfill`, data, { timeout: 300000 })
}

export function getNegativeSuggestions(params) {
  return request.get(`${BASE}/negative-suggestions`, { params })
}

export function getKeywordSyncStatus(shopId) {
  return request.get(`${BASE}/sync-status`, { params: { shop_id: shopId } })
}

export function translateKeywords(keywords) {
  return request.post(`${BASE}/translate-keywords`, { keywords }, { timeout: 60000 })
}

export function getKeywordCampaigns(params) {
  return request.get(`${BASE}/keyword-campaigns`, { params })
}

export function excludeKeyword(data) {
  return request.post(`${BASE}/exclude-keyword`, data)
}
