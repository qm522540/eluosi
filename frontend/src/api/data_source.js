import request from './index'

// 查单店所有数据源 (Level 1 + Level 2 状态)
export function getShopDataSources(shopId) {
  return request.get(`/data-sources/shop/${shopId}`)
}

// 跨店共享数据源 (SEO 引擎等)
export function getSharedDataSources() {
  return request.get('/data-sources/shared')
}

// 改店铺 API 总开关 (Level 1, 紧急止血)
// body: { enabled, reason?, auto_resume_hours? }
export function patchShopApiSwitch(shopId, body) {
  return request.patch(`/data-sources/shop/${shopId}/api-switch`, body)
}

// 改单数据源开关 (Level 2)
// body: { enabled, reason? }
export function patchDataSource(shopId, sourceKey, body) {
  return request.patch(`/data-sources/shop/${shopId}/${sourceKey}`, body)
}
