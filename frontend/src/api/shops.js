import request from './index'

export function getShops(params) {
  return request.get('/shops', { params })
}

export function createShop(data) {
  return request.post('/shops', data)
}

export function getShop(shopId) {
  return request.get(`/shops/${shopId}`)
}

export function updateShop(shopId, data) {
  return request.put(`/shops/${shopId}`, data)
}

export function deleteShop(shopId) {
  return request.delete(`/shops/${shopId}`)
}

export function testConnection(shopId) {
  return request.post(`/shops/${shopId}/test-connection`)
}
