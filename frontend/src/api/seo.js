import request from './index'

const BASE = '/seo'

/** 店铺候选词清单 + 4 格汇总 */
export function getSeoCandidates(shopId, params) {
  return request.get(`${BASE}/shop/${shopId}/candidates`, { params })
}

/** 跨商品爆款词：带订单且多个商品未覆盖，改一个词全店受益 */
export function getChampionKeywords(shopId, params) {
  return request.get(`${BASE}/shop/${shopId}/champion-keywords`, { params })
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

/** AI 生成商品俄语描述（走 GLM，5-15 秒）— 后端自取候选词全集，不需要前端勾选 */
export function generateSeoDescription(shopId, productId, maxCandidates = 50) {
  return request.post(
    `${BASE}/shop/${shopId}/generate-description`,
    { product_id: productId, max_candidates: maxCandidates },
    { timeout: 60000 },
  )
}

/** 店铺 SEO 健康分诊断 + Top 缺词 */
export function getSeoHealth(shopId, params) {
  return request.get(`${BASE}/shop/${shopId}/health`, { params })
}

/** 单商品全部未覆盖候选词（健康诊断行展开用） */
export function getProductMissingCandidates(shopId, productId) {
  return request.get(`${BASE}/shop/${shopId}/product/${productId}/missing-candidates`)
}

/** AI 生成标题历史（分页） */
export function getGeneratedTitles(shopId, params) {
  return request.get(`${BASE}/shop/${shopId}/generated-titles`, { params })
}

/** 标记"已应用到商品"建立 ROI 对比基线（二期用） */
export function applyGeneratedTitle(shopId, generatedId) {
  return request.post(`${BASE}/shop/${shopId}/generated-titles/${generatedId}/apply`)
}

/** 关键词表现追踪 — 本期 vs 上期 环比 + 下滑预警 */
export function getKeywordTracking(shopId, params) {
  return request.get(`${BASE}/shop/${shopId}/keyword-tracking`, { params })
}

/** 改标题 Before/After ROI 对比 — applied_at 切割前后 N 天 */
export function getRoiReport(shopId, params) {
  return request.get(`${BASE}/shop/${shopId}/roi-report`, { params })
}

/** 单核心词下钻：Top N 商品靠这词带流量 */
export function getKeywordTrackingSkus(shopId, params) {
  return request.get(`${BASE}/shop/${shopId}/keyword-tracking/skus`, { params })
}

/** 店级关键词聚合：每行=关键词跨商品汇总 */
export function getKeywordRollup(shopId, params) {
  return request.get(`${BASE}/shop/${shopId}/keyword-rollup`, { params })
}

/** 单关键词下钻：该词在各商品的贡献分项 */
export function getKeywordRollupProducts(shopId, params) {
  return request.get(`${BASE}/shop/${shopId}/keyword-rollup/products`, { params })
}

/** 按商品看 Tab 的关键词聚合主视图（走候选池，含付费/自然/类目扩散） */
export function getCandidatesRollup(shopId, params) {
  return request.get(`${BASE}/shop/${shopId}/candidates-rollup`, { params })
}

/** 候选池单关键词下钻到商品明细 */
export function getCandidatesRollupProducts(shopId, params) {
  return request.get(`${BASE}/shop/${shopId}/candidates-rollup/products`, { params })
}

/** 类目推断证据：该类目下对该关键词真实搜中的 Top N 商品（点"推荐理由"Tag 弹 Modal） */
export function getCandidatesRollupCategoryEvidence(shopId, params) {
  return request.get(`${BASE}/shop/${shopId}/candidates-rollup/category-evidence`, { params })
}

/** 跨店同款证据：同 products.sku 在其他 shop 对该关键词真实搜中明细（点跨店 Tag 弹 Modal） */
export function getCandidatesRollupCrossShopEvidence(shopId, params) {
  return request.get(`${BASE}/shop/${shopId}/candidates-rollup/cross-shop-evidence`, { params })
}
