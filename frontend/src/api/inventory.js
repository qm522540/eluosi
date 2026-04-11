import request from './index'

/** 获取店铺库存联动规则 */
export const getLinkageRule = (shopId) =>
  request.get(`/inventory/linkage-rule/${shopId}`)

/** 更新店铺库存联动规则 */
export const updateLinkageRule = (shopId, data) =>
  request.put(`/inventory/linkage-rule/${shopId}`, data)

/** 获取店铺商品库存状态列表 */
export const getShopStocks = (shopId, status) =>
  request.get(`/inventory/stocks/${shopId}`, {
    params: status ? { status } : {},
  })

/** 手动触发库存联动检查 */
export const manualLinkageCheck = (shopId) =>
  request.post(`/inventory/linkage-check/${shopId}`)
