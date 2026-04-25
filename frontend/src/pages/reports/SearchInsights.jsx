import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Typography, Card, Table, Button, Space, Select, Row, Col, Statistic,
  Segmented, message, Tooltip, Alert, Input,
} from 'antd'
import {
  KeyOutlined, SyncOutlined, SearchOutlined, InfoCircleOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { getShops } from '@/api/shops'
import { getShopSearchInsights, refreshShopSearchInsights } from '@/api/search_insights'

const { Title, Text } = Typography
const { Option } = Select

const PLATFORM_LABEL = { wb: 'WB', ozon: 'Ozon' }
const DATE_PRESETS = [
  { label: '近7天', value: '7d' },
  { label: '近30天', value: '30d' },
]

const SearchInsights = () => {
  const navigate = useNavigate()
  const [shops, setShops] = useState([])
  const [shopId, setShopId] = useState(null)
  const [shopPlatform, setShopPlatform] = useState(null)
  const [datePreset, setDatePreset] = useState('30d')
  const [keyword, setKeyword] = useState('')

  const [loading, setLoading] = useState(false)
  const [data, setData] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const [subscriptionMsg, setSubscriptionMsg] = useState('')

  useEffect(() => {
    getShops({ page: 1, page_size: 100 })
      .then(r => setShops((r.data?.items || []).filter(s => ['wb', 'ozon'].includes(s.platform))))
      .catch(() => setShops([]))
  }, [])

  const getDateRange = useCallback(() => {
    const days = datePreset === '30d' ? 30 : 7
    return {
      date_from: dayjs().subtract(days, 'day').format('YYYY-MM-DD'),
      date_to: dayjs().subtract(1, 'day').format('YYYY-MM-DD'),
    }
  }, [datePreset])

  const fetchData = useCallback(async () => {
    if (!shopId) return
    const range = getDateRange()
    const params = {
      ...range,
      page: 1,
      size: 2000,
      sort_by: 'frequency',
      sort_order: 'desc',
    }
    if (keyword.trim()) params.keyword = keyword.trim()
    setLoading(true)
    try {
      const res = await getShopSearchInsights(shopId, params)
      setData(res.data)
    } catch (err) {
      message.error(err.message || '加载失败')
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [shopId, getDateRange, keyword])

  useEffect(() => {
    if (shopId) fetchData()
  }, [shopId, datePreset, fetchData])

  const handleShopChange = (val) => {
    const s = shops.find(x => x.id === val)
    setShopId(val)
    setShopPlatform(s?.platform || null)
    setSubscriptionMsg('')
  }

  const handleRefresh = async () => {
    if (!shopId) { message.warning('请先选择店铺'); return }
    setRefreshing(true)
    setSubscriptionMsg('')
    try {
      const res = await refreshShopSearchInsights(shopId, datePreset === '30d' ? 30 : 7)
      message.success(`同步完成：写入 ${res.data?.synced_queries || 0} 条`)
      fetchData()
    } catch (err) {
      const code = err.response?.data?.code
      const msg = err.response?.data?.msg || err.message || '同步失败'
      if (code === 93001) {
        setSubscriptionMsg(msg)
      } else {
        message.error(msg)
      }
    } finally {
      setRefreshing(false)
    }
  }

  const totals = data?.totals
  const items = data?.items || []

  const columns = [
    {
      title: '关键词', dataIndex: 'query_text', key: 'query_text',
      width: 260, ellipsis: true,
      render: v => <Text strong>{v}</Text>,
    },
    {
      title: <Tooltip title="搜索次数 = 用户搜该词时，你商品在搜索结果列表中出现的累计次数（WB frequency / Ozon unique_search_users）。SKU 级字段：同一个词命中你多个 SKU 会按 SKU 累计。注意：含同一用户跨 SKU 重复计数（平台无跨 SKU 去重数据）。">
        搜索次数 <InfoCircleOutlined style={{ color: '#999' }} />
      </Tooltip>,
      dataIndex: 'frequency', key: 'frequency', width: 110, align: 'right',
      sorter: (a, b) => a.frequency - b.frequency,
      render: v => (v || 0).toLocaleString(),
    },
    {
      title: <Tooltip title="曝光 = 用户搜词后，真正滚动看见你商品卡片的累计次数（WB 不返此字段为 0；Ozon unique_view_users）。恒有 曝光 ≤ 搜索次数（出现 ≥ 滚动看到）。「优化建议·店级 TOP」页累加的就是这个数。">
        曝光 <InfoCircleOutlined style={{ color: '#999' }} />
      </Tooltip>,
      dataIndex: 'impressions', key: 'impressions', width: 90, align: 'right',
      sorter: (a, b) => a.impressions - b.impressions,
      render: v => (v || 0).toLocaleString(),
    },
    {
      title: <Tooltip title="曝光比例 = 曝光 / 搜索次数。反映「你商品在搜索结果里被翻到的程度」 — 越高说明排名越靠前 / 相关性越强。但「相关性强」不等于「适合卖」：曝光高 + 点击 0 反而是错配信号（用户看到了但不是他要的）。最终适合度要看下单率（下单 / 曝光）。">
        曝光比例 <InfoCircleOutlined style={{ color: '#999' }} />
      </Tooltip>,
      key: 'view_rate', width: 110, align: 'right',
      sorter: (a, b) => {
        const ra = a.frequency ? a.impressions / a.frequency : 0
        const rb = b.frequency ? b.impressions / b.frequency : 0
        return ra - rb
      },
      render: (_, r) => {
        if (!r.frequency) return '-'
        const pct = r.impressions / r.frequency * 100
        let color = '#f5222d'
        if (pct >= 60) color = '#52c41a'
        else if (pct >= 30) color = '#faad14'
        return <Text style={{ color, fontWeight: 500 }}>{pct.toFixed(0)}%</Text>
      },
    },
    {
      title: shopPlatform === 'ozon'
        ? <Tooltip title="Ozon 接口不返点击数据，列固定为 —"><span>点击</span></Tooltip>
        : '点击',
      dataIndex: 'clicks', key: 'clicks', width: 65, align: 'right',
      render: v => shopPlatform === 'ozon' ? <Text type="secondary">—</Text> : (v || 0),
    },
    {
      title: shopPlatform === 'ozon'
        ? <Tooltip title="Ozon 接口不返加购数据，列固定为 —"><span>加购</span></Tooltip>
        : '加购',
      dataIndex: 'add_to_cart', key: 'add_to_cart', width: 65, align: 'right',
      render: v => shopPlatform === 'ozon' ? <Text type="secondary">—</Text> : (v || 0),
    },
    { title: '下单', dataIndex: 'orders', key: 'orders', width: 65, align: 'right' },
    {
      title: '销售额(₽)', dataIndex: 'revenue', key: 'revenue', width: 105, align: 'right',
      render: v => (v || 0).toFixed(2),
    },
    { title: '商品数', dataIndex: 'sku_count', key: 'sku_count', width: 75, align: 'right' },
  ]

  return (
    <div>
      <Title level={3}>
        <KeyOutlined /> 搜索词洞察
        <Text type="secondary" style={{ fontSize: 14, marginLeft: 12, fontWeight: 'normal' }}>
          用户搜哪些词找到我的商品 (SEO 流量)
        </Text>
        <Button
          type="link"
          size="small"
          style={{ marginLeft: 12, fontSize: 13 }}
          onClick={() => navigate('/seo/optimize')}
        >
          → 进入 SEO 优化建议
        </Button>
      </Title>

      <Alert
        type="info" showIcon style={{ marginBottom: 16 }}
        message="此功能依赖搜索词分析订阅（WB / Ozon 各自独立）"
        description={
          <div style={{ fontSize: 12, lineHeight: 1.7 }}>
            <div>
              · <strong>WB</strong>：需开通 <strong>Jam 订阅</strong>，调
              <code> /search-report/product/search-texts</code>
            </div>
            <div>
              · <strong>Ozon</strong>：需开通 <strong>搜索词分析订阅（Premium 或 Premium Plus，按 Ozon 后台档位）</strong>，调
              <code> /v1/analytics/product-queries/details</code>
            </div>
            <div style={{ marginTop: 4, color: '#d46b08' }}>
              ⚠ <strong>订阅过期 / 降级也会 403</strong>，不只是"没开过"。
              如果之前能用现在不行，请去平台后台检查订阅状态（很可能已开过但失效）。
            </div>
            <div style={{ marginTop: 4, color: '#999' }}>
              订阅生效后点「同步数据」拉取近 N 天，之后查本地表秒出。
            </div>
          </div>
        }
      />

      {subscriptionMsg && (
        <Alert
          type="warning" showIcon style={{ marginBottom: 16 }} closable
          message={
            shopPlatform === 'wb'
              ? 'WB 店铺订阅状态异常 — 请去 WB 后台检查 Jam 订阅'
              : shopPlatform === 'ozon'
                ? 'Ozon 店铺订阅状态异常 — 请去 Ozon 后台检查搜索词分析订阅'
                : '该店铺订阅状态异常 — 请去平台后台检查'
          }
          description={
            <div style={{ fontSize: 12, lineHeight: 1.7 }}>
              <div>
                {shopPlatform === 'wb'
                  ? '可能原因：① 未开通 WB Jam 订阅；② 之前开过但已过期 — 请到 WB 后台续费。'
                  : shopPlatform === 'ozon'
                    ? '可能原因：① 未开通 Ozon 搜索词分析专项（Premium / Premium Plus）；② 之前开过但已过期或降级 — 请到 Ozon 后台账号订阅页检查档位。'
                    : '可能原因：未开通对应平台的搜索词分析订阅，或订阅已过期 / 降级。'}
              </div>
              <details style={{ marginTop: 6 }}>
                <summary style={{ cursor: 'pointer', color: '#999', fontSize: 11 }}>
                  展开技术细节（平台返回的原始错误）
                </summary>
                <pre style={{
                  fontSize: 11, background: '#fafafa',
                  padding: 6, marginTop: 4, borderRadius: 4,
                  whiteSpace: 'pre-wrap',
                  maxHeight: 100, overflow: 'auto',
                }}>
                  {subscriptionMsg}
                </pre>
              </details>
            </div>
          }
          onClose={() => setSubscriptionMsg('')}
        />
      )}

      <Card style={{ marginBottom: 16 }}>
        <Space wrap size={12}>
          <Select
            placeholder="选择店铺 (WB/Ozon)"
            style={{ width: 280 }}
            value={shopId}
            onChange={handleShopChange}
            showSearch optionFilterProp="children"
          >
            {shops.map(s => (
              <Option key={s.id} value={s.id}>
                [{PLATFORM_LABEL[s.platform] || s.platform}] {s.name}
              </Option>
            ))}
          </Select>
          <Segmented
            options={DATE_PRESETS}
            value={datePreset}
            onChange={setDatePreset}
          />
          <Input
            placeholder="搜索关键词"
            prefix={<SearchOutlined />}
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            onPressEnter={fetchData}
            allowClear
            style={{ width: 200 }}
          />
          <Button
            type="primary" icon={<SyncOutlined spin={refreshing} />}
            onClick={handleRefresh} loading={refreshing}
            disabled={!shopId}
          >
            同步数据
          </Button>
        </Space>
      </Card>

      {shopId && (
        <>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col xs={12} md={6}>
              <Card size="small"><Statistic title="搜索词总数" value={totals?.query_count || 0} /></Card>
            </Col>
            <Col xs={12} md={6}>
              <Card size="small"><Statistic title="总搜索次数" value={totals?.frequency || 0} /></Card>
            </Col>
            <Col xs={12} md={6}>
              <Card size="small"><Statistic title="下单数" value={totals?.orders || 0} /></Card>
            </Col>
            <Col xs={12} md={6}>
              <Card size="small">
                <Statistic title="销售额" value={totals?.revenue || 0} suffix="₽" precision={2} />
              </Card>
            </Col>
          </Row>

          <Card
            title={
              <Text type="secondary" style={{ fontSize: 13 }}>
                数据范围：{totals?.date_from} ~ {totals?.date_to}
              </Text>
            }
          >
            {totals?.query_count > items.length && (
              <Alert
                type="info" showIcon style={{ marginBottom: 12 }}
                message={
                  <span>
                    数据量超过 2000 条，按搜索次数降序仅展示前 <Text strong>{items.length}</Text> 条；
                    全店共 <Text strong>{totals.query_count}</Text> 个搜索词。要看更长尾的低频词请用上方搜索框定位。
                  </span>
                }
              />
            )}
            <Table
              rowKey="query_text"
              columns={columns}
              dataSource={items}
              loading={loading}
              pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: [20, 50, 100] }}
              size="small"
              scroll={{ x: 'max-content' }}
              locale={{
                emptyText: shopId
                  ? '暂无数据。点"同步数据"拉取最近搜索词（需要订阅）'
                  : '请先选择店铺',
              }}
            />
          </Card>
        </>
      )}
    </div>
  )
}

export default SearchInsights
