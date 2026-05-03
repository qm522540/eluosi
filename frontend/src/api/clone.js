import request from './index'

const BASE = '/clone'

// ==================== §5.1 任务管理 ====================

export const createTask = (data) => request.post(`${BASE}/tasks`, data)

export const listTasks = (params) => request.get(`${BASE}/tasks`, { params })

export const getTask = (taskId) => request.get(`${BASE}/tasks/${taskId}`)

export const updateTask = (taskId, data) => request.put(`${BASE}/tasks/${taskId}`, data)

export const enableTask = (taskId) => request.post(`${BASE}/tasks/${taskId}/enable`)

export const disableTask = (taskId) => request.post(`${BASE}/tasks/${taskId}/disable`)

// 11.2: 干跑预览 — 返候选清单不写库
export const scanPreview = (taskId) =>
  request.post(`${BASE}/tasks/${taskId}/scan-preview`, null, { timeout: 180000 })

// scan-now: selectedSkus=null 兼容旧"全量立项"; 传数组只立项 preview 勾选的
// localSkuOverrides: { source_sku_id → 自定义 A 店 SKU }, preview 行用户改的
export const scanNow = (taskId, selectedSkus = null, localSkuOverrides = null) => {
  const body = {}
  if (selectedSkus) body.selected_skus = selectedSkus
  if (localSkuOverrides) body.local_sku_overrides = localSkuOverrides
  return request.post(`${BASE}/tasks/${taskId}/scan-now`, body, { timeout: 180000 })
}

export const deleteTask = (taskId) => request.delete(`${BASE}/tasks/${taskId}`)

// ==================== §5.2 待审核 ====================

export const listPending = (params) => request.get(`${BASE}/pending`, { params })

export const approvePending = (id) => request.post(`${BASE}/pending/${id}/approve`)

export const rejectPending = (id, reject_reason) =>
  request.post(`${BASE}/pending/${id}/reject`, { reject_reason })

export const restorePending = (id) => request.post(`${BASE}/pending/${id}/restore`)

export const updatePendingPayload = (id, proposed_payload) =>
  request.put(`${BASE}/pending/${id}`, { proposed_payload })

export const batchApprove = (ids) =>
  request.post(`${BASE}/pending/approve-batch`, { ids })

export const batchReject = (ids, reject_reason) =>
  request.post(`${BASE}/pending/reject-batch`, { ids, reject_reason })

// 简化设计: 待审核页"发布"按钮直接触发 — 单条 / 批量
export const publishPending = (id) => request.post(`${BASE}/pending/${id}/publish`)

// 同步发布 — 单条用; 后端直接 await publish_engine, 立刻拿到上架结果 (耗时 20-30 秒)
export const publishPendingSync = (id) =>
  request.post(`${BASE}/pending/${id}/publish-sync`, null, { timeout: 90000 })

export const batchPublish = (ids) =>
  request.post(`${BASE}/pending/publish-batch`, { ids })

// 物理 DELETE 3 表 (pending + listing + product) - 不可逆, 删后下次扫描重新采
export const batchDeletePending = (ids) =>
  request.post(`${BASE}/pending/delete-batch`, { ids })

// ==================== §5.3 日志 ====================

export const listLogs = (params) => request.get(`${BASE}/logs`, { params })

// ==================== §5.4 辅助 ====================

export const listAvailableShops = () => request.get(`${BASE}/available-shops`)

export const checkCategoryCoverage = (taskId) =>
  request.get(`${BASE}/category-coverage/${taskId}`)
