import request from './index'

export function healthCheck() {
  return request.get('/system/health')
}
