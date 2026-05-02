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
export const scanNow = (taskId, selectedSkus = null) =>
  request.post(`${BASE}/tasks/${taskId}/scan-now`,
    selectedSkus ? { selected_skus: selectedSkus } : {},
    { timeout: 180000 })

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

// ==================== §5.3 日志 ====================

export const listLogs = (params) => request.get(`${BASE}/logs`, { params })

// ==================== §5.4 辅助 ====================

export const listAvailableShops = () => request.get(`${BASE}/available-shops`)

export const checkCategoryCoverage = (taskId) =>
  request.get(`${BASE}/category-coverage/${taskId}`)
