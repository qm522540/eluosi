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
