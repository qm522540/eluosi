import request from './index'

const BASE = '/region-stats'

export function getRegionRanking(params) {
  return request.get(`${BASE}/ranking`, { params })
}

export function getRegionTrend(params) {
  return request.get(`${BASE}/trend`, { params })
}

export function backfillRegions(data) {
  return request.post(`${BASE}/backfill`, data, { timeout: 300000 })
}

export function getRegionSyncStatus(shopId) {
  return request.get(`${BASE}/sync-status`, { params: { shop_id: shopId } })
}

/** 某地区 TOP SKU 明细（决策关该地区配送时看是关哪几个 SKU） */
export function getRegionDetail(params) {
  return request.get(`${BASE}/region-detail`, { params, timeout: 30000 })
}
