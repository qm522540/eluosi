import request from './index'

/** 获取商品列表 */
export function getProducts(params = {}) {
  return request.get('/products', { params })
}

/** 获取商品详情 */
export function getProduct(id) {
  return request.get(`/products/${id}`)
}

/** 创建商品 */
export function createProduct(data) {
  return request.post('/products', data)
}

/** 更新商品 */
export function updateProduct(id, data) {
  return request.put(`/products/${id}`, data)
}

/** 快速更新净毛利率 */
export function updateProductMargin(id, netMargin) {
  return request.patch(`/products/${id}/margin`, { net_margin: netMargin })
}

/** 删除商品 */
export function deleteProduct(id) {
  return request.delete(`/products/${id}`)
}

/** 检查是否需要同步 */
export function checkSyncNeeded(shopId) {
  return request.get('/products/sync/check', { params: { shop_id: shopId } })
}

/** 触发商品同步 */
export function syncProducts(shopId, force = false) {
  return request.post('/products/sync', { shop_id: shopId, force })
}

/** AI改写商品描述 */
export function generateDescription(listingId, targetPlatform) {
  return request.post(`/products/listings/${listingId}/generate-description`, {
    listing_id: listingId,
    target_platform: targetPlatform,
  })
}

/** 提交铺货任务 */
export function spreadProducts(data) {
  return request.post('/products/spread', data)
}

/** 获取铺货记录 */
export function getSpreadRecords(params = {}) {
  return request.get('/products/spread/records', { params })
}

/** 获取Listing列表 */
export function getListings(params = {}) {
  return request.get('/products/listings/list', { params })
}

/** 更新Listing */
export function updateListing(id, data) {
  return request.put(`/products/listings/${id}`, data)
}

/** 删除Listing */
export function deleteListing(id) {
  return request.delete(`/products/listings/${id}`)
}
