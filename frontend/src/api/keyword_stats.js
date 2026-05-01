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

export function translateKeywords(keywords, dbOnly = true) {
  // dbOnly 默认 true：用户面调用永远只查 DB 缓存，避免 Kimi 阻塞 batch 响应
  // 没翻译过的词后端会留原词，前端 hasZh 判断为 false → 显示"翻译中..."
  // 后台预填脚本应显式传 dbOnly=false 走 Kimi
  return request.post(`${BASE}/translate-keywords`, { keywords, db_only: dbOnly }, { timeout: 10000 })
}

export function getKeywordCampaigns(params) {
  return request.get(`${BASE}/keyword-campaigns`, { params })
}

export function excludeKeyword(data) {
  return request.post(`${BASE}/exclude-keyword`, data)
}

// 关键词效能评级规则（租户级自定义）
export function getEfficiencyRules() {
  return request.get(`${BASE}/efficiency-rules`)
}

export function setEfficiencyRules(rules) {
  return request.put(`${BASE}/efficiency-rules`, rules)
}

export function resetEfficiencyRules() {
  return request.post(`${BASE}/efficiency-rules/reset`)
}

export function getWordChanges(shopId) {
  return request.get(`${BASE}/word-changes`, { params: { shop_id: shopId } })
}

export function updateTranslation(keyword, translation) {
  return request.post(`${BASE}/update-translation`, { keyword, translation })
}
