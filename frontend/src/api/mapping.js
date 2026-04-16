import request from './index'

const BASE = '/mapping'

// ========== §3 本地分类 ==========

export function listLocalCategories(params = {}) {
  return request.get(`${BASE}/local-categories`, { params })
}

export function getLocalCategoryTree() {
  return request.get(`${BASE}/local-categories/tree`)
}

export function createLocalCategory(data) {
  return request.post(`${BASE}/local-categories`, data)
}

export function updateLocalCategory(catId, data) {
  return request.put(`${BASE}/local-categories/${catId}`, data)
}

export function deleteLocalCategory(catId) {
  return request.delete(`${BASE}/local-categories/${catId}`)
}

// ========== §4 品类映射 ==========

export function listCategoryMappings(params = {}) {
  return request.get(`${BASE}/category-mappings`, { params })
}

export function upsertCategoryMapping(data) {
  return request.post(`${BASE}/category-mappings`, data)
}

export function confirmCategoryMapping(mappingId, patch = {}) {
  return request.post(`${BASE}/category-mappings/${mappingId}/confirm`, patch)
}

export function deleteCategoryMapping(mappingId) {
  return request.delete(`${BASE}/category-mappings/${mappingId}`)
}

// ========== §5 属性映射 ==========

export function listAttributeMappings(params = {}) {
  return request.get(`${BASE}/attribute-mappings`, { params })
}

export function upsertAttributeMapping(data) {
  return request.post(`${BASE}/attribute-mappings`, data)
}

export function confirmAttributeMapping(mappingId, patch = {}) {
  return request.post(`${BASE}/attribute-mappings/${mappingId}/confirm`, patch)
}

export function deleteAttributeMapping(mappingId) {
  return request.delete(`${BASE}/attribute-mappings/${mappingId}`)
}

// ========== §6 属性值映射 ==========

export function listAttributeValueMappings(attributeMappingId) {
  return request.get(`${BASE}/attribute-value-mappings`, {
    params: { attribute_mapping_id: attributeMappingId },
  })
}

export function upsertAttributeValueMapping(data) {
  return request.post(`${BASE}/attribute-value-mappings`, data)
}

export function confirmAttributeValueMapping(mappingId, patch = {}) {
  return request.post(`${BASE}/attribute-value-mappings/${mappingId}/confirm`, patch)
}

export function deleteAttributeValueMapping(mappingId) {
  return request.delete(`${BASE}/attribute-value-mappings/${mappingId}`)
}

// ========== §7 AI 推荐 ==========

// §7.1 AI 推荐品类映射：后端会自动写入 category_platform_mappings，前端刷新 §4.1 列表即可
// timeout 放宽到 30s，通常 5-15s
export function aiSuggestCategory(data) {
  return request.post(`${BASE}/ai-suggest/category`, data, { timeout: 30000 })
}

// §7.2 AI 推荐属性映射。前置：该本地分类在该平台必须已有品类映射
export function aiSuggestAttributes(data) {
  return request.post(`${BASE}/ai-suggest/attributes`, data, { timeout: 30000 })
}
