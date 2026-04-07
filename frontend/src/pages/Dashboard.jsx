import { useState, useEffect } from 'react'
import { Row, Col, Card, Statistic, Tag, Typography, Spin, message } from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ShopOutlined,
  FundOutlined,
  ShoppingCartOutlined,
  DollarOutlined,
} from '@ant-design/icons'
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
    } catch (err) {
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

      {/* 系统状态 */}
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

      {/* 数据概览卡片 */}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="店铺总数"
              value={0}
              prefix={<ShopOutlined />}
              suffix="个"
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="广告活动"
              value={0}
              prefix={<FundOutlined />}
              suffix="个"
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="在售商品"
              value={0}
              prefix={<ShoppingCartOutlined />}
              suffix="件"
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="今日ROI"
              value={'--'}
              prefix={<DollarOutlined />}
            />
          </Card>
        </Col>
      </Row>

      {/* 三平台ROI概览（占位） */}
      <Row gutter={[16, 16]} style={{ marginTop: 24 }}>
        <Col xs={24} lg={8}>
          <Card title="Wildberries" size="small" style={{ minHeight: 200 }}>
            <Text type="secondary">暂无数据，请先配置店铺</Text>
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="Ozon" size="small" style={{ minHeight: 200 }}>
            <Text type="secondary">暂无数据，请先配置店铺</Text>
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="Yandex Market" size="small" style={{ minHeight: 200 }}>
            <Text type="secondary">暂无数据，请先配置店铺</Text>
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default Dashboard
