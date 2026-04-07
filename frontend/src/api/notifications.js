import request from './index'

export function getNotifications(params) {
  return request.get('/notifications', { params })
}

export function markNotificationRead(notificationId) {
  return request.put(`/notifications/${notificationId}/read`)
}

export function sendPendingNotifications() {
  return request.post('/notifications/send-pending')
}
