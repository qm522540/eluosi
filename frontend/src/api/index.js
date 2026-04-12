import axios from 'axios'
import { useAuthStore } from '@/stores/authStore'

const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: 15000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器：自动携带token
request.interceptors.request.use(
  (config) => {
    const token = useAuthStore.getState().token
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截器：统一处理错误
request.interceptors.response.use(
  (response) => {
    // blob 响应（文件下载）直接返回，不走 code 校验
    if (response.config.responseType === 'blob') {
      return response.data
    }
    const res = response.data
    // 后端统一响应格式: {code, msg, data, timestamp}
    if (res.code !== 0) {
      // 仅 token 过期/失效才自动跳转登录页（20002=TOKEN_EXPIRED, 20003=TOKEN_INVALID）
      // 注意：20001=AUTH_FAILED（邮箱密码错）不应跳转，因为用户已经在登录页，
      // 跳转会触发整页刷新导致 message.error 提示被吞掉，看起来"点登录没反应"
      if (res.code === 20002 || res.code === 20003) {
        // 已经在登录页就不要重复跳转，避免覆盖错误提示
        if (window.location.pathname !== '/login') {
          useAuthStore.getState().logout()
          window.location.href = '/login'
        }
      }
      return Promise.reject(new Error(res.msg || '请求失败'))
    }
    return res
  },
  (error) => {
    if (error.response) {
      const status = error.response.status
      // 401/403 认证类错误：仅在非登录页才跳转
      if ((status === 401 || status === 403)
          && window.location.pathname !== '/login') {
        useAuthStore.getState().logout()
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  }
)

export default request
