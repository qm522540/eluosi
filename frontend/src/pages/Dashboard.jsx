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
  DashboardOutlined,
  ArrowRightOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { healthCheck } from '@/api/system'
import { getShops } from '@/api/shops'
import { getTodaySummaryByShop } from '@/api/ads'
import { getSeoHealth } from '@/api/seo'
import { useAuthStore } from '@/stores/authStore'

const { Title, Text } = Typography

const GRADE_COLOR = { poor: '#cf1322', fair: '#faad14', good: '#3f8600' }

const Dashboard = () => {
  const navigate = useNavigate()
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

  // SEO 健康概览（各店铺均分 + Top 3 待优化）
  const [seoByShop, setSeoByShop] = useState([])
  const [seoLoading, setSeoLoading] = useState(false)
  const loadSeoHealth = useCallback(async () => {
    setSeoLoading(true)
    try {
      const r = await getShops({ page: 1, page_size: 100 })
      const shops = (r.data?.items || []).filter(s => ['wb', 'ozon'].includes(s.platform))
      const results = await Promise.all(shops.map(async (s) => {
        try {
          const hr = await getSeoHealth(s.id, { sort: 'score_asc', page: 1, size: 3 })
          return { ...s, seo: hr.data }
        } catch {
          return { ...s, seo: null }
        }
      }))
      setSeoByShop(results)
    } finally {
      setSeoLoading(false)
    }
  }, [])
  useEffect(() => { loadSeoHealth() }, [loadSeoHealth])

  const classifyScore = (s) => (s >= 70 ? 'good' : s >= 40 ? 'fair' : 'poor')

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

      {/* SEO 健康概览（挪到页面最下方，首屏先看今日数据） */}
      <Card
        size="small"
        style={{ marginTop: 16, marginBottom: 16, background: '#fafbff', borderColor: '#e6edff' }}
        bodyStyle={{ padding: '12px 16px' }}
        title={
          <Space>
            <DashboardOutlined />
            <Text strong style={{ fontSize: 13 }}>SEO 健康概览</Text>
            <Text type="secondary" style={{ fontSize: 11 }}>
              评分越低越需要优化 · 点卡片跳诊断页
            </Text>
          </Space>
        }
        extra={
          <Button size="small" icon={<SyncOutlined spin={seoLoading} />} onClick={loadSeoHealth}>
            刷新
          </Button>
        }
      >
        <Spin spinning={seoLoading}>
          {seoByShop.length === 0 && !seoLoading ? (
            <Text type="secondary" style={{ fontSize: 12 }}>暂无 WB / Ozon 店铺</Text>
          ) : (
            <Row gutter={[12, 12]}>
              {seoByShop.map(s => {
                const t = s.seo?.totals
                const items = s.seo?.items || []
                const grade = t ? classifyScore(t.avg_score) : 'fair'
                return (
                  <Col xs={24} sm={12} lg={8} key={s.id}>
                    <Card
                      size="small"
                      hoverable
                      onClick={() => navigate(`/seo/health?shopId=${s.id}`)}
                      bodyStyle={{ padding: 10 }}
                      style={{ cursor: 'pointer' }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
                        <Space>
                          <Tag color={PLATFORM_COLOR[s.platform]} style={{ fontSize: 11, margin: 0 }}>
                            {PLATFORM_LABEL[s.platform] || s.platform}
                          </Tag>
                          <Text strong style={{ fontSize: 13 }}>{s.name}</Text>
                        </Space>
                        {t ? (
                          <div style={{
                            minWidth: 52, padding: '2px 8px', textAlign: 'center',
                            background: '#fafbff',
                            border: '1px solid #e6edff',
                            borderRadius: 3,
                          }}>
                            <div style={{ fontSize: 16, fontWeight: 600, color: GRADE_COLOR[grade], lineHeight: 1.1 }}>
                              {t.avg_score?.toFixed(1) || '-'}
                            </div>
                            <div style={{ fontSize: 10, color: '#999' }}>均分</div>
                          </div>
                        ) : null}
                      </div>
                      {t ? (
                        <>
                          <Space size={8} style={{ marginBottom: 8, fontSize: 11 }}>
                            <Tag color="error" style={{ margin: 0 }}>差 {t.poor}</Tag>
                            <Tag color="warning" style={{ margin: 0 }}>中 {t.fair}</Tag>
                            <Tag color="success" style={{ margin: 0 }}>优 {t.good}</Tag>
                            <Text type="secondary" style={{ fontSize: 11 }}>共 {t.all} 个商品</Text>
                          </Space>
                          {items.length > 0 && (
                            <div style={{ fontSize: 11, color: '#666' }}>
                              <Text type="secondary" style={{ fontSize: 11 }}>最差 Top 3：</Text>
                              {items.slice(0, 3).map((p, i) => (
                                <div key={p.product_id} style={{ marginTop: 2, display: 'flex', alignItems: 'center', gap: 4 }}>
                                  <Text style={{ fontSize: 11, flex: 1, minWidth: 0 }} ellipsis={{ tooltip: p.product_name || `pid ${p.product_id}` }}>
                                    {i + 1}. {p.product_name || `pid ${p.product_id}`}
                                  </Text>
                                  <Tag color={GRADE_COLOR[p.grade]} style={{ fontSize: 10, margin: 0, padding: '0 4px', flexShrink: 0 }}>
                                    {p.score}
                                  </Tag>
                                </div>
                              ))}
                            </div>
                          )}
                          <Button
                            type="link"
                            size="small"
                            style={{ padding: 0, marginTop: 4, fontSize: 11 }}
                            onClick={(e) => { e.stopPropagation(); navigate(`/seo/health?shopId=${s.id}`) }}
                          >
                            去 SEO 健康诊断 <ArrowRightOutlined />
                          </Button>
                        </>
                      ) : (
                        <Text type="secondary" style={{ fontSize: 12 }}>暂无 SEO 数据</Text>
                      )}
                    </Card>
                  </Col>
                )
              })}
            </Row>
          )}
        </Spin>
      </Card>
    </div>
  )
}

export default Dashboard
