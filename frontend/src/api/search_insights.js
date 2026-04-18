import request from './index'

const BASE = '/search-insights'

/** 店铺维度：按关键词聚合 + 标签分类 + 分页 */
export function getShopSearchInsights(shopId, params) {
  return request.get(`${BASE}/shop/${shopId}`, { params })
}

/** 单商品维度：编辑 Drawer Tab 用 */
export function getProductSearchInsights(productId, params) {
  return request.get(`${BASE}/product/${productId}`, { params })
}

/** 手动触发同步（按 shop_id 单店铺） */
export function refreshShopSearchInsights(shopId, days = 7) {
  return request.post(`${BASE}/shop/${shopId}/refresh`, null, {
    params: { days },
    timeout: 120000,
  })
}
