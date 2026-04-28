import { useState, useEffect } from 'react'
import { Card, Tag, Typography, Spin, message } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'
import { healthCheck } from '@/api/system'
import { useAuthStore } from '@/stores/authStore'

const { Title, Text } = Typography

const Dashboard = () => {
  const user = useAuthStore((s) => s.user)
  const [health, setHealth] = useState(null)
  const [healthLoading, setHealthLoading] = useState(true)

  useEffect(() => {
    checkHealth()
  }, [])

  const checkHealth = async () => {
    setHealthLoading(true)
    try {
      const res = await healthCheck()
      setHealth(res.data)
    } catch {
      setHealth({ status: 'error' })
      message.error('后端服务连接失败')
    } finally {
      setHealthLoading(false)
    }
  }

  return (
    <div>
      <Title level={4} style={{ marginBottom: 24 }}>
        欢迎回来，{user?.username || '用户'}
      </Title>

      <Card size="small" style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Text strong>系统状态：</Text>
          {healthLoading ? (
            <Spin size="small" />
          ) : health?.status === 'ok' ? (
            <Tag icon={<CheckCircleOutlined />} color="success">
              服务正常 ({health.service})
            </Tag>
          ) : (
            <Tag icon={<CloseCircleOutlined />} color="error">
              服务异常
            </Tag>
          )}
          <a onClick={checkHealth} style={{ marginLeft: 8 }}>刷新</a>
        </div>
      </Card>
    </div>
  )
}

export default Dashboard
