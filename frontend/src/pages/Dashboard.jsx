import { useState, useEffect, useCallback } from 'react'
import { Row, Col, Card, Statistic, Tag, Typography, Spin, message, Button, Tooltip, Space } from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ShopOutlined,
  FundOutlined,
  ShoppingCartOutlined,
  DollarOutlined,
  SyncOutlined,
} from '@ant-design/icons'
import { healthCheck } from '@/api/system'
import { getShops } from '@/api/shops'
import { getTodaySummaryByShop } from '@/api/ads'
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

  // 全店铺今日实时汇总（5 分钟缓存）
  const [shopsToday, setShopsToday] = useState([])
  const [todayLoading, setTodayLoading] = useState(false)
  const loadShopsToday = useCallback(async (refresh = false) => {
    setTodayLoading(true)
    try {
      const r = await getShops({ page: 1, page_size: 100 })
      const shops = r.data?.items || []
      const results = await Promise.all(shops.map(async (s) => {
        try {
          const tr = await getTodaySummaryByShop(s.id, refresh)
          return { ...s, today: tr.data }
        } catch {
          return { ...s, today: null }
        }
      }))
      setShopsToday(results)
    } finally {
      setTodayLoading(false)
    }
  }, [])
  useEffect(() => { loadShopsToday() }, [loadShopsToday])

  const fmt = (v) => (v ?? 0).toLocaleString()
  const totalSpend = shopsToday.reduce((s, x) => s + (x.today?.spend || 0), 0)
  const totalOrders = shopsToday.reduce((s, x) => s + (x.today?.orders || 0), 0)
  const totalRevenue = shopsToday.reduce((s, x) => s + (x.today?.revenue || 0), 0)
  const totalRoas = totalSpend > 0 ? (totalRevenue / totalSpend).toFixed(2) : 0
  const PLATFORM_LABEL = { wb: 'WB', ozon: 'Ozon', yandex: 'Yandex' }
  const PLATFORM_COLOR = { wb: '#cb11ab', ozon: '#005bff', yandex: '#fc3f1d' }

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

      {/* 全店铺今日汇总 */}
      <Card
        size="small"
        style={{ marginBottom: 16, background: '#fafbff', borderColor: '#e6edff' }}
        bodyStyle={{ padding: '12px 16px' }}
        title={
          <Space>
            <Text strong style={{ fontSize: 13 }}>今日全店铺汇总</Text>
            <Tooltip title="WB 数据有几小时延迟，早上常空，下午陆续就位。Ozon/Yandex 后续接入。">
              <Text type="secondary" style={{ fontSize: 11, cursor: 'help' }}>
                {shopsToday[0]?.today?.today_date || ''}
              </Text>
            </Tooltip>
          </Space>
        }
        extra={
          <Button size="small" icon={<SyncOutlined spin={todayLoading} />}
            onClick={() => loadShopsToday(true)}>
            刷新
          </Button>
        }
      >
        <Spin spinning={todayLoading}>
          <Row gutter={[16, 16]}>
            <Col xs={12} sm={6}>
              <Statistic
                title={<span style={{ fontSize: 12, color: '#999' }}>店铺数</span>}
                value={shopsToday.length}
                prefix={<ShopOutlined />}
                valueStyle={{ fontSize: 20, fontWeight: 600 }}
              />
            </Col>
            <Col xs={12} sm={6}>
              <Statistic
                title={<span style={{ fontSize: 12, color: '#999' }}>今日花费</span>}
                value={`₽${fmt(totalSpend.toFixed(2))}`}
                prefix={<DollarOutlined />}
                valueStyle={{ fontSize: 20, fontWeight: 600 }}
              />
            </Col>
            <Col xs={12} sm={6}>
              <Statistic
                title={<span style={{ fontSize: 12, color: '#999' }}>今日订单</span>}
                value={totalOrders}
                prefix={<ShoppingCartOutlined />}
                valueStyle={{ fontSize: 20, fontWeight: 600, color: '#52c41a' }}
              />
            </Col>
            <Col xs={12} sm={6}>
              <Statistic
                title={<span style={{ fontSize: 12, color: '#999' }}>今日 ROAS</span>}
                value={totalRoas !== 0 ? `${totalRoas}x` : '-'}
                prefix={<FundOutlined />}
                valueStyle={{
                  fontSize: 20, fontWeight: 600,
                  color: totalRoas >= 2 ? '#52c41a' : totalRoas > 0 ? '#faad14' : '#999',
                }}
              />
            </Col>
          </Row>
        </Spin>
      </Card>

      {/* 各店铺横向卡片 */}
      <Row gutter={[16, 16]}>
        {shopsToday.length === 0 && !todayLoading && (
          <Col span={24}>
            <Card>
              <Text type="secondary">暂无店铺，请先到「设置 → 店铺管理」添加店铺</Text>
            </Card>
          </Col>
        )}
        {shopsToday.map(s => (
          <Col xs={24} sm={12} lg={8} key={s.id}>
            <Card
              size="small"
              hoverable
              title={
                <Space>
                  <Tag color={PLATFORM_COLOR[s.platform]} style={{ fontSize: 11, margin: 0 }}>
                    {PLATFORM_LABEL[s.platform] || s.platform}
                  </Tag>
                  <Text strong>{s.name}</Text>
                </Space>
              }
              style={{ minHeight: 180 }}
            >
              {s.today?.platform === 'wb' ? (
                <Row gutter={[8, 8]}>
                  <Col span={12}>
                    <div style={{ fontSize: 11, color: '#999' }}>花费</div>
                    <div style={{ fontSize: 18, fontWeight: 600 }}>
                      ₽{fmt(s.today.spend)}
                    </div>
                  </Col>
                  <Col span={12}>
                    <div style={{ fontSize: 11, color: '#999' }}>订单</div>
                    <div style={{ fontSize: 18, fontWeight: 600, color: '#52c41a' }}>
                      {s.today.orders}
                    </div>
                  </Col>
                  <Col span={12}>
                    <div style={{ fontSize: 11, color: '#999' }}>曝光</div>
                    <div style={{ fontSize: 14 }}>{fmt(s.today.views)}</div>
                  </Col>
                  <Col span={12}>
                    <div style={{ fontSize: 11, color: '#999' }}>点击</div>
                    <div style={{ fontSize: 14 }}>{fmt(s.today.clicks)}</div>
                  </Col>
                  <Col span={12}>
                    <div style={{ fontSize: 11, color: '#999' }}>CTR</div>
                    <div style={{ fontSize: 14 }}>{s.today.ctr || 0}%</div>
                  </Col>
                  <Col span={12}>
                    <div style={{ fontSize: 11, color: '#999' }}>ROAS</div>
                    <div style={{
                      fontSize: 14, fontWeight: 600,
                      color: s.today.roas >= 2 ? '#52c41a' : s.today.roas > 0 ? '#faad14' : '#999',
                    }}>
                      {s.today.roas ? `${s.today.roas}x` : '-'}
                    </div>
                  </Col>
                  <Col span={24} style={{ marginTop: 4, fontSize: 11, color: '#bbb' }}>
                    {s.today.active_campaign_count} 个 active 活动
                  </Col>
                </Row>
              ) : (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {s.today?.msg || '暂无当日数据'}
                </Text>
              )}
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  )
}

export default Dashboard
