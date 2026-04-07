import { Navigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'

const AuthRoute = ({ children }) => {
  const token = useAuthStore((s) => s.token)

  if (!token) {
    return <Navigate to="/login" replace />
  }

  return children
}

export default AuthRoute
