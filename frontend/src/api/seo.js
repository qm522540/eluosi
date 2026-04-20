import request from './index'

const BASE = '/seo'

/** 店铺候选词清单 + 4 格汇总 */
export function getSeoCandidates(shopId, params) {
  return request.get(`${BASE}/shop/${shopId}/candidates`, { params })
}

/** 手动触发引擎扫描（付费反哺 + 类目聚合），可能较慢 */
export function refreshSeo(shopId, body = {}) {
  return request.post(`${BASE}/shop/${shopId}/refresh`, body, {
    timeout: 120000,
  })
}

/** 单条候选加入标题候选（只改候选池状态，不改 products.title） */
export function adoptSeoCandidate(shopId, candidateId) {
  return request.post(`${BASE}/shop/${shopId}/candidates/${candidateId}/adopt`)
}

/** 批量忽略候选 */
export function batchIgnoreCandidates(shopId, ids) {
  return request.post(`${BASE}/shop/${shopId}/candidates/batch-ignore`, { ids })
}

/** AI 融合候选词生成新俄语标题（走 GLM，可能 5-30 秒） */
export function generateSeoTitle(shopId, productId, candidateIds) {
  return request.post(
    `${BASE}/shop/${shopId}/generate-title`,
    { product_id: productId, candidate_ids: candidateIds },
    { timeout: 60000 },
  )
}

/** 店铺 SEO 健康分诊断 + Top 缺词 */
export function getSeoHealth(shopId, params) {
  return request.get(`${BASE}/shop/${shopId}/health`, { params })
}

/** AI 生成标题历史（分页） */
export function getGeneratedTitles(shopId, params) {
  return request.get(`${BASE}/shop/${shopId}/generated-titles`, { params })
}

/** 标记"已应用到商品"建立 ROI 对比基线（二期用） */
export function applyGeneratedTitle(shopId, generatedId) {
  return request.post(`${BASE}/shop/${shopId}/generated-titles/${generatedId}/apply`)
}
