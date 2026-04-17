import { useState, useEffect, useCallback } from 'react'
import {
  Typography, Card, Table, Button, Space, Select, Row, Col, Statistic, Tag,
  Empty, Spin, message, Tooltip, DatePicker, Segmented, Progress, Badge,
} from 'antd'
import {
  EnvironmentOutlined, SyncOutlined, SearchOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import { getShops } from '@/api/shops'
import { getRegionRanking, getRegionTrend, getRegionSyncStatus, backfillRegions } from '@/api/region_stats'

const { Title, Text } = Typography
const { Option } = Select

const PLATFORM_LABEL = { wb: 'WB', ozon: 'Ozon', yandex: 'YM' }

const DATE_PRESETS = [
  { label: '近7天', value: '7d' },
  { label: '近30天', value: '30d' },
  { label: '按月', value: 'month' },
]

const RegionSales = () => {
  const [shops, setShops] = useState([])
  const [shopId, setShopId] = useState(null)
  const [shopPlatform, setShopPlatform] = useState(null)
  const [datePreset, setDatePreset] = useState('7d')
  const [monthValue, setMonthValue] = useState(null)
  const [searched, setSearched] = useState(false)

  const [loading, setLoading] = useState(false)
  const [rankingData, setRankingData] = useState(null)
  const [trendData, setTrendData] = useState(null)
  const [trendMetric, setTrendMetric] = useState('orders')
  const [syncStatus, setSyncStatus] = useState(null)
  const [backfilling, setBackfilling] = useState(false)

  useEffect(() => {
    getShops({ page: 1, page_size: 100 })
      .then(r => setShops(r.data?.items || []))
      .catch(() => setShops([]))
  }, [])

  const getDateRange = useCallback(() => {
    if (datePreset === 'month' && monthValue) {
      return {
        date_from: monthValue.startOf('month').format('YYYY-MM-DD'),
        date_to: monthValue.endOf('month').format('YYYY-MM-DD'),
      }
    }
    const days = datePreset === '30d' ? 30 : 7
    return {
      date_from: dayjs().subtract(days, 'day').format('YYYY-MM-DD'),
      date_to: dayjs().subtract(1, 'day').format('YYYY-MM-DD'),
    }
  }, [datePreset, monthValue])

  const handleSearch = () => {
    if (!shopId) { message.warning('请先选择店铺'); return }
    setSearched(true)
    fetchAll()
  }

  const fetchAll = useCallback(async () => {
    if (!shopId) return
    const range = getDateRange()
    setLoading(true)
    try {
      const [rankRes, trendRes, syncRes] = await Promise.allSettled([
        getRegionRanking({ shop_id: shopId, ...range, limit: 50 }),
        getRegionTrend({ shop_id: shopId, ...range, top: 5, metric: trendMetric }),
        getRegionSyncStatus(shopId),
      ])
      if (rankRes.status === 'fulfilled') setRankingData(rankRes.value.data)
      if (trendRes.status === 'fulfilled') setTrendData(trendRes.value.data)
      if (syncRes.status === 'fulfilled') setSyncStatus(syncRes.value.data)
    } catch {
      // 后端未就绪
    } finally {
      setLoading(false)
    }
  }, [shopId, getDateRange, trendMetric])

  useEffect(() => {
    if (searched) fetchAll()
  }, [searched, fetchAll])

  const handleBackfill = async () => {
    if (!shopId) return
    setBackfilling(true)
    try {
      const res = await backfillRegions({ shop_id: shopId, days: 90 })
      message.success(res.data?.msg || '回填任务已提交')
    } catch (err) {
      message.error(err.message || '回填失败')
    } finally {
      setBackfilling(false)
    }
  }

  const items = rankingData?.items || []
  const totals = rankingData?.totals || {}

  // 饼图配置：TOP 8 + 其他
  const pieOption = items.length > 0 ? (() => {
    const top8 = items.slice(0, 8)
    const rest = items.slice(8)
    const pieData = top8.map(r => ({ name: r.region_name_zh || r.region_name, value: r.revenue }))
    if (rest.length) {
      pieData.push({ name: `其他 ${rest.length} 个地区`, value: rest.reduce((s, r) => s + r.revenue, 0) })
    }
    return {
      tooltip: { trigger: 'item', formatter: '{b}: {c}₽ ({d}%)' },
      legend: { type: 'scroll', bottom: 0 },
      series: [{
        type: 'pie',
        radius: ['35%', '65%'],
        label: { formatter: '{b}\n{d}%', fontSize: 11 },
        data: pieData,
        emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,0.2)' } },
      }],
    }
  })() : null

  // 趋势图
  const trendOption = trendData ? {
    tooltip: { trigger: 'axis' },
    legend: { data: (trendData.series || []).map(s => s.region_name), type: 'scroll', bottom: 0 },
    grid: { left: 50, right: 20, top: 10, bottom: 50 },
    xAxis: { type: 'category', data: trendData.dates || [] },
    yAxis: { type: 'value' },
    series: (trendData.series || []).map(s => ({
      name: s.region_name,
      type: 'line',
      smooth: true,
      data: s.values,
      emphasis: { focus: 'series' },
    })),
  } : null

  const metricLabel = { orders: '订单', revenue: '销售额（₽）' }

  // 排行表列
  const columns = [
    {
      title: '#', key: 'index', width: 50,
      render: (_, __, i) => {
        const rank = i + 1
        if (rank <= 3) return <Badge count={rank} style={{ backgroundColor: rank === 1 ? '#f5222d' : rank === 2 ? '#fa8c16' : '#faad14' }} />
        return rank
      },
    },
    {
      title: '地区', key: 'region', width: 200,
      render: (_, r) => (
        <Space>
          <EnvironmentOutlined style={{ color: '#1677ff' }} />
          <div>
            <Text strong>{r.region_name_zh || r.region_name}</Text>
            {r.region_name_zh && r.region_name_zh !== r.region_name && (
              <div><Text type="secondary" style={{ fontSize: 11 }}>{r.region_name}</Text></div>
            )}
          </div>
        </Space>
      ),
    },
    {
      title: '订单数', dataIndex: 'orders', key: 'orders', width: 100,
      sorter: (a, b) => a.orders - b.orders,
      defaultSortOrder: 'descend',
      render: v => <Text strong>{v?.toLocaleString()}</Text>,
    },
    {
      title: '销售额', dataIndex: 'revenue', key: 'revenue', width: 130,
      sorter: (a, b) => a.revenue - b.revenue,
      render: v => `${v?.toLocaleString()} ₽`,
    },
    {
      title: '客单价', dataIndex: 'avg_price', key: 'avg_price', width: 100,
      sorter: (a, b) => a.avg_price - b.avg_price,
      render: v => `${v?.toFixed(0)} ₽`,
    },
    {
      title: '退货率', dataIndex: 'return_rate', key: 'return_rate', width: 90,
      sorter: (a, b) => (a.return_rate || 0) - (b.return_rate || 0),
      render: v => {
        if (v == null) return <Text type="secondary">-</Text>
        const color = v > 10 ? '#f5222d' : v > 5 ? '#fa8c16' : '#52c41a'
        return <Text style={{ color }}>{v}%</Text>
      },
    },
    {
      title: '订单占比', dataIndex: 'orders_pct', key: 'orders_pct', width: 140,
      render: v => v != null ? (
        <Space>
          <Progress percent={v} size="small" style={{ width: 80 }} showInfo={false}
            strokeColor={v > 15 ? '#1677ff' : '#d9d9d9'} />
          <Text style={{ fontSize: 12 }}>{v}%</Text>
        </Space>
      ) : '-',
    },
    {
      title: '销售占比', dataIndex: 'revenue_pct', key: 'revenue_pct', width: 90,
      render: v => v != null ? `${v}%` : '-',
    },
  ]

  function renderFilterBar() {
    return (
      <Card size="small" style={{ marginBottom: 16 }} bodyStyle={{ padding: '12px 16px' }}>
        <Row gutter={8} align="middle" wrap>
          <Col>
            <Select
              style={{ width: 260 }}
              value={shopId}
              onChange={(id, opt) => {
                setShopId(id ?? null)
                setShopPlatform(opt?.platform || null)
                setSearched(false)
              }}
              placeholder="选择平台 · 店铺"
              allowClear showSearch optionFilterProp="children"
            >
              {['wb', 'ozon', 'yandex'].map(plat => {
                const list = shops.filter(s => s.platform === plat)
                if (!list.length) return null
                return (
                  <Select.OptGroup key={plat} label={PLATFORM_LABEL[plat]}>
                    {list.map(s => (
                      <Option key={s.id} value={s.id} platform={plat}>
                        {PLATFORM_LABEL[plat]} · {s.name}
                      </Option>
                    ))}
                  </Select.OptGroup>
                )
              })}
            </Select>
          </Col>
          <Col>
            <Segmented value={datePreset} onChange={v => { setDatePreset(v); setSearched(false) }} options={DATE_PRESETS} />
          </Col>
          {datePreset === 'month' && (
            <Col>
              <DatePicker picker="month" value={monthValue} onChange={v => { setMonthValue(v); setSearched(false) }}
                placeholder="选择月份" disabledDate={d => d.isAfter(dayjs())} />
            </Col>
          )}
          <Col>
            <Button type="primary" icon={<SearchOutlined />} disabled={!shopId} onClick={handleSearch}>查询</Button>
          </Col>
          <Col flex={1} />
          {syncStatus && (
            <Col>
              <Text type="secondary" style={{ fontSize: 12 }}>
                数据截至 {syncStatus.latest_date} · 共 {syncStatus.total_days} 天
              </Text>
            </Col>
          )}
          <Col>
            <Tooltip title="回填最近 90 天地区销售数据">
              <Button size="small" icon={<SyncOutlined spin={backfilling} />} loading={backfilling} onClick={handleBackfill}>
                回填历史
              </Button>
            </Tooltip>
          </Col>
        </Row>
      </Card>
    )
  }

  if (!searched) {
    return (
      <div>
        <Title level={4}><EnvironmentOutlined /> 地区销售分析</Title>
        {renderFilterBar()}
        <Card><Empty description="请选择店铺后点击查询" /></Card>
      </div>
    )
  }

  return (
    <div>
      <Title level={4}><EnvironmentOutlined /> 地区销售分析</Title>
      {renderFilterBar()}

      <Spin spinning={loading}>
        {/* 汇总卡片 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          {[
            { title: '覆盖地区', value: totals.regions, color: '#1677ff' },
            { title: '总订单', value: totals.orders, color: undefined },
            { title: '总销售额', value: totals.revenue, suffix: '₽', color: '#722ed1' },
            { title: '平均客单价', value: totals.avg_price?.toFixed(0), suffix: '₽', color: '#fa8c16' },
          ].map((item, i) => (
            <Col xs={12} sm={6} key={i}>
              <Card size="small" bodyStyle={{ padding: 12 }}>
                <Statistic title={item.title} value={item.value ?? '-'} suffix={item.suffix}
                  valueStyle={{ fontSize: 22, color: item.color }} />
              </Card>
            </Col>
          ))}
        </Row>

        {/* 饼图 + 趋势图 并排 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col xs={24} lg={10}>
            <Card size="small" title="销售额地区分布">
              {pieOption ? (
                <ReactECharts option={pieOption} style={{ height: 320 }} />
              ) : (
                <Empty description="暂无数据" style={{ padding: 40 }} />
              )}
            </Card>
          </Col>
          <Col xs={24} lg={14}>
            <Card
              size="small"
              title={`TOP 5 地区${metricLabel[trendMetric]}趋势`}
              extra={
                <Segmented size="small" value={trendMetric}
                  onChange={v => setTrendMetric(v)}
                  options={[
                    { label: '订单', value: 'orders' },
                    { label: '销售额', value: 'revenue' },
                  ]}
                />
              }
            >
              {trendOption ? (
                <ReactECharts option={trendOption} style={{ height: 320 }} />
              ) : (
                <Empty description="暂无趋势数据" style={{ padding: 40 }} />
              )}
            </Card>
          </Col>
        </Row>

        {/* 排行表 */}
        <Card
          size="small"
          title={
            <Space>
              <Text strong>地区排行</Text>
              <Text type="secondary" style={{ fontWeight: 400, fontSize: 13 }}>
                {rankingData?.date_from} ~ {rankingData?.date_to}
              </Text>
            </Space>
          }
        >
          <Table
            rowKey="region_name"
            size="middle"
            dataSource={items}
            columns={columns}
            loading={loading}
            pagination={items.length > 20 ? { pageSize: 20, showTotal: t => `共 ${t} 个地区` } : false}
            locale={{
              emptyText: (
                <Empty
                  description={
                    syncStatus?.total_days
                      ? '该时间范围内无地区销售数据'
                      : <span>尚未同步地区数据，点击右上角 <Text strong>回填历史</Text> 开始</span>
                  }
                />
              ),
            }}
          />
        </Card>
      </Spin>
    </div>
  )
}

export default RegionSales
