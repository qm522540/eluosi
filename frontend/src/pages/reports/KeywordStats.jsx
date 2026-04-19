import { useState, useEffect, useCallback } from 'react'
import {
  Typography, Card, Table, Button, Space, Select, Row, Col, Statistic, Tag,
  Empty, Spin, Alert, message, Tooltip, DatePicker, Radio, Segmented, Badge,
  Drawer, Popconfirm,
} from 'antd'
import {
  KeyOutlined, DownloadOutlined, ReloadOutlined, SyncOutlined,
  StarFilled, BulbOutlined, WarningFilled, SearchOutlined,
  StopOutlined, EyeOutlined, SettingOutlined,
} from '@ant-design/icons'
import EfficiencyRulesDrawer from './EfficiencyRulesDrawer'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import { getShops } from '@/api/shops'
import {
  getKeywordSummary, getKeywordTrend, getKeywordSkuDetail,
  getNegativeSuggestions, getKeywordSyncStatus, backfillKeywords,
  translateKeywords, getKeywordCampaigns, excludeKeyword,
} from '@/api/keyword_stats'
import { getAutoExcludeSummary } from '@/api/ads'

const { Title, Text } = Typography
const { Option } = Select

const PLATFORM_LABEL = { wb: 'WB', ozon: 'Ozon', yandex: 'YM' }

const EFFICIENCY_MAP = {
  star: { color: 'green', icon: <StarFilled />, label: '高效词', tip: '点击率达标 且 CPC 不高于平均，性价比高（具体阈值见效能规则）' },
  potential: { color: 'blue', icon: <BulbOutlined />, label: '潜力词', tip: '点击率达标 但 曝光偏少，建议加大投放（具体阈值见效能规则）' },
  waste: { color: 'red', icon: <WarningFilled />, label: '浪费词', tip: '点击率过低 但 花费超过平均，建议屏蔽（具体阈值见效能规则）' },
  normal: { color: 'default', icon: null, label: '普通', tip: '表现一般，暂不需要特殊处理' },
  new: { color: 'cyan', icon: <EyeOutlined />, label: '新词', tip: '曝光不足门槛，数据不可信，建议先观察（曝光门槛见效能规则）' },
}

const EFFICIENCY_FILTER_OPTS = [
  { label: '全部', value: '' },
  { label: '⭐ 高效', value: 'star' },
  { label: '💡 潜力', value: 'potential' },
  { label: '🗑️ 浪费', value: 'waste' },
  { label: '普通', value: 'normal' },
  { label: '👁 新词', value: 'new' },
]

const SORT_OPTS = [
  { label: '花费 ↓', value: 'spend|desc' },
  { label: '花费 ↑', value: 'spend|asc' },
  { label: '曝光 ↓', value: 'impressions|desc' },
  { label: '点击 ↓', value: 'clicks|desc' },
  { label: 'CTR ↓', value: 'ctr|desc' },
  { label: 'CPC ↑', value: 'cpc|asc' },
]

// 日期范围快捷项
const DATE_PRESETS = [
  { label: '近7天', value: '7d' },
  { label: '近30天', value: '30d' },
  { label: '按月', value: 'month' },
]

const KeywordStats = () => {
  // 筛选
  const [shops, setShops] = useState([])
  const [shopId, setShopId] = useState(null)
  const [shopPlatform, setShopPlatform] = useState(null)
  const [datePreset, setDatePreset] = useState('7d')
  const [monthValue, setMonthValue] = useState(null)
  const [searched, setSearched] = useState(false)

  // 数据
  const [loading, setLoading] = useState(false)
  const [summaryData, setSummaryData] = useState(null)
  const [trendData, setTrendData] = useState(null)
  const [trendMetric, setTrendMetric] = useState('impressions')
  const [negativeSugs, setNegativeSugs] = useState([])
  const [kwTranslations, setKwTranslations] = useState({})
  // 关键词关联活动商品 Drawer
  const [kwDetailDrawer, setKwDetailDrawer] = useState(false)
  const [kwDetailKeyword, setKwDetailKeyword] = useState('')
  const [kwDetailEfficiency, setKwDetailEfficiency] = useState('normal')
  const [kwDetailData, setKwDetailData] = useState(null)
  const [kwDetailLoading, setKwDetailLoading] = useState(false)
  const [excluding, setExcluding] = useState(null) // campaign_id:nm_id being excluded
  const [syncStatus, setSyncStatus] = useState(null)
  const [page, setPage] = useState(1)
  const [sortBy, setSortBy] = useState('spend')
  const [sortOrder, setSortOrder] = useState('desc')
  const [efficiencyFilter, setEfficiencyFilter] = useState('')
  const [keywordSearch, setKeywordSearch] = useState('')

  // SKU 展开
  const [expandedKeys, setExpandedKeys] = useState([])
  const [skuDetailMap, setSkuDetailMap] = useState({})
  const [skuLoadingMap, setSkuLoadingMap] = useState({})

  // 初始化/回填
  const [backfilling, setBackfilling] = useState(false)

  // 效能规则 Drawer
  const [rulesDrawerOpen, setRulesDrawerOpen] = useState(false)
  // 自动屏蔽店铺成果（顶部条，按当前选中店铺过滤 — 规则 4）
  const [autoExcludeSummary, setAutoExcludeSummaryState] = useState(null)
  const [autoExcludeExpand, setAutoExcludeExpand] = useState(false)
  useEffect(() => {
    if (!shopId) { setAutoExcludeSummaryState(null); return }
    getAutoExcludeSummary(shopId, 30).then(r => setAutoExcludeSummaryState(r.data)).catch(() => {})
  }, [shopId])

  useEffect(() => {
    getShops({ page: 1, page_size: 100 })
      .then(r => setShops(r.data?.items || []))
      .catch(() => setShops([]))
  }, [])

  const getDateRange = useCallback(() => {
    if (datePreset === 'month' && monthValue) {
      const m = monthValue
      return { date_from: m.startOf('month').format('YYYY-MM-DD'), date_to: m.endOf('month').format('YYYY-MM-DD') }
    }
    const days = datePreset === '30d' ? 30 : 7
    return {
      date_from: dayjs().subtract(days, 'day').format('YYYY-MM-DD'),
      date_to: dayjs().subtract(1, 'day').format('YYYY-MM-DD'),
    }
  }, [datePreset, monthValue])

  const handleSearch = async () => {
    if (!shopId) { message.warning('请先选择店铺'); return }
    setSearched(true)
    setPage(1)
    setExpandedKeys([])
    setSkuDetailMap({})
    fetchAll()
  }

  const fetchAll = useCallback(async () => {
    if (!shopId) return
    const range = getDateRange()
    setLoading(true)
    try {
      const [sumRes, trendRes, negRes, syncRes] = await Promise.allSettled([
        getKeywordSummary({
          shop_id: shopId, ...range,
          sort_by: sortBy, sort_order: sortOrder,
          page, size: 50,
          keyword: keywordSearch || undefined,
          efficiency: efficiencyFilter || undefined,
        }),
        getKeywordTrend({ shop_id: shopId, ...range, top: 10, metric: trendMetric }),
        getNegativeSuggestions({ shop_id: shopId, ...range }),
        getKeywordSyncStatus(shopId),
      ])
      if (sumRes.status === 'fulfilled') {
        setSummaryData(sumRes.value.data)
        // 自动翻译当前页的关键词（异步，不阻塞展示）
        const kws = (sumRes.value.data?.items || []).map(it => it.keyword).filter(Boolean)
        if (kws.length > 0) {
          translateKeywords(kws).then(res => {
            setKwTranslations(prev => ({ ...prev, ...(res.data || {}) }))
          }).catch(() => {})
        }
      }
      if (trendRes.status === 'fulfilled') setTrendData(trendRes.value.data)
      if (negRes.status === 'fulfilled') setNegativeSugs(negRes.value.data?.items || [])
      if (syncRes.status === 'fulfilled') setSyncStatus(syncRes.value.data)
    } catch {
      // 后端未就绪时展示空态
    } finally {
      setLoading(false)
    }
  }, [shopId, getDateRange, sortBy, sortOrder, page, trendMetric, keywordSearch, efficiencyFilter])

  useEffect(() => {
    if (searched) fetchAll()
  }, [searched, fetchAll])

  const handleViewKeywordCampaigns = async (keyword, efficiency) => {
    setKwDetailKeyword(keyword)
    setKwDetailEfficiency(efficiency || 'normal')
    setKwDetailDrawer(true)
    setKwDetailLoading(true)
    setKwDetailData(null)
    try {
      const range = getDateRange()
      const res = await getKeywordCampaigns({ shop_id: shopId, keyword, ...range })
      setKwDetailData(res.data)
    } catch {
      message.error('查询关联活动失败')
    } finally {
      setKwDetailLoading(false)
    }
  }

  const handleExcludeKeyword = async (campaignId, nmId, keyword) => {
    const key = `${campaignId}:${nmId}`
    setExcluding(key)
    try {
      const res = await excludeKeyword({ shop_id: shopId, campaign_id: campaignId, nm_id: nmId, keyword })
      if (res.data?.already_excluded) {
        message.info('该关键词已在屏蔽列表中')
      } else {
        message.success(res.data?.msg || '已屏蔽')
      }
    } catch (e) {
      message.error(e?.response?.data?.msg || '屏蔽失败')
    } finally {
      setExcluding(null)
    }
  }

  const handleBackfill = async () => {
    if (!shopId) return
    setBackfilling(true)
    try {
      const res = await backfillKeywords({ shop_id: shopId, days: 90 })
      message.success(res.data?.msg || '回填任务已提交')
    } catch (err) {
      message.error(err.message || '回填失败')
    } finally {
      setBackfilling(false)
    }
  }

  // SKU 展开（仅 Ozon）
  const handleExpand = async (expanded, record) => {
    const kw = record.keyword
    if (!expanded) {
      setExpandedKeys(keys => keys.filter(k => k !== kw))
      return
    }
    setExpandedKeys(keys => [...keys, kw])
    if (skuDetailMap[kw] !== undefined) return
    setSkuLoadingMap(m => ({ ...m, [kw]: true }))
    try {
      const range = getDateRange()
      const res = await getKeywordSkuDetail({ shop_id: shopId, keyword: kw, ...range })
      setSkuDetailMap(m => ({ ...m, [kw]: res.data?.items || [] }))
    } catch {
      setSkuDetailMap(m => ({ ...m, [kw]: [] }))
    } finally {
      setSkuLoadingMap(m => ({ ...m, [kw]: false }))
    }
  }

  // 趋势图配置
  const trendOption = trendData ? {
    tooltip: { trigger: 'axis' },
    legend: { data: (trendData.series || []).map(s => s.keyword), type: 'scroll', bottom: 0 },
    grid: { left: 50, right: 20, top: 10, bottom: 50 },
    xAxis: { type: 'category', data: trendData.dates || [] },
    yAxis: { type: 'value' },
    series: (trendData.series || []).map(s => ({
      name: s.keyword,
      type: 'line',
      smooth: true,
      data: s.values,
      emphasis: { focus: 'series' },
    })),
  } : null

  const metricLabel = { impressions: '曝光', clicks: '点击', spend: '花费（₽）' }

  // 表格列
  const columns = [
    {
      title: '#', key: 'index', width: 50,
      render: (_, __, i) => (page - 1) * 50 + i + 1,
    },
    {
      title: '关键词', dataIndex: 'keyword', key: 'keyword',
      render: (v, record) => {
        const zh = kwTranslations[v]
        return (
          <Space size={6}>
            <Tooltip title={zh && zh !== v ? `中文：${zh}` : '翻译加载中...'}>
              <Text strong style={{ fontSize: 13, cursor: 'help' }}>{v}</Text>
            </Tooltip>
            <Tooltip title="查看引用此关键词的活动和商品">
              <Button size="small" type="text" icon={<EyeOutlined />}
                style={{ fontSize: 11, padding: '0 4px', height: 20 }}
                onClick={() => handleViewKeywordCampaigns(v, record.efficiency)} />
            </Tooltip>
          </Space>
        )
      },
    },
    {
      title: <Tooltip title="根据曝光门槛 + 点击率 + 花费自动评级。详细阈值见效能规则"><span style={{ cursor: 'help' }}>效能 <span style={{ fontSize: 10, color: '#bbb' }}>ⓘ</span></span></Tooltip>,
      dataIndex: 'efficiency', key: 'efficiency', width: 100,
      render: (v) => {
        const cfg = EFFICIENCY_MAP[v] || EFFICIENCY_MAP.normal
        return (
          <Tooltip title={cfg.tip}>
            <Tag color={cfg.color} icon={cfg.icon} style={{ cursor: 'help' }}>{cfg.label}</Tag>
          </Tooltip>
        )
      },
    },
    {
      title: <Tooltip title="广告被展示给用户的次数（用列头上方的排序选择器切换）"><span style={{ cursor: 'help' }}>曝光 <span style={{ fontSize: 10, color: '#bbb' }}>ⓘ</span></span></Tooltip>,
      dataIndex: 'impressions', key: 'impressions', width: 100,
      render: v => v?.toLocaleString(),
    },
    {
      title: <Tooltip title="用户看到广告后点击进入商品页的次数"><span style={{ cursor: 'help' }}>点击 <span style={{ fontSize: 10, color: '#bbb' }}>ⓘ</span></span></Tooltip>,
      dataIndex: 'clicks', key: 'clicks', width: 80,
      render: v => v?.toLocaleString(),
    },
    {
      title: <Tooltip title="点击率 = 点击 ÷ 曝光 × 100%，反映广告吸引力"><span style={{ cursor: 'help' }}>CTR <span style={{ fontSize: 10, color: '#bbb' }}>ⓘ</span></span></Tooltip>,
      dataIndex: 'ctr', key: 'ctr', width: 80,
      render: v => v != null ? `${v}%` : '-',
    },
    {
      title: <Tooltip title="该关键词在选定日期范围内的广告总花费"><span style={{ cursor: 'help' }}>花费 <span style={{ fontSize: 10, color: '#bbb' }}>ⓘ</span></span></Tooltip>,
      dataIndex: 'spend', key: 'spend', width: 110,
      render: v => v != null ? <Text strong>{v.toLocaleString()} ₽</Text> : '-',
    },
    {
      title: <Tooltip title="单次点击成本 = 花费 ÷ 点击数，越低越好"><span style={{ cursor: 'help' }}>CPC <span style={{ fontSize: 10, color: '#bbb' }}>ⓘ</span></span></Tooltip>,
      dataIndex: 'cpc', key: 'cpc', width: 80,
      render: v => v != null ? `${v} ₽` : '-',
    },
    {
      title: <Tooltip title="该关键词花费占总花费的百分比"><span style={{ cursor: 'help' }}>占比 <span style={{ fontSize: 10, color: '#bbb' }}>ⓘ</span></span></Tooltip>,
      dataIndex: 'spend_pct', key: 'spend_pct', width: 80,
      render: v => v != null ? `${v}%` : '-',
    },
  ]

  const isOzon = shopPlatform === 'ozon'

  // 未搜索态
  if (!searched) {
    return (
      <div>
        <Title level={4}><KeyOutlined /> 关键词统计</Title>
        {renderFilterBar()}
        <Card>
          <Empty description="请选择店铺后点击查询" />
        </Card>
      </div>
    )
  }

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
              allowClear
              showSearch
              optionFilterProp="children"
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
            <Segmented
              value={datePreset}
              onChange={v => { setDatePreset(v) }}
              options={DATE_PRESETS}
            />
          </Col>
          {datePreset === 'month' && (
            <Col>
              <DatePicker
                picker="month"
                value={monthValue}
                onChange={v => { setMonthValue(v) }}
                placeholder="选择月份"
                disabledDate={d => d.isAfter(dayjs())}
              />
            </Col>
          )}
          <Col>
            <Button type="primary" icon={<SearchOutlined />} disabled={!shopId} onClick={handleSearch}>
              查询
            </Button>
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
            <Tooltip title="回填最近 90 天历史数据（首次使用需点一次）">
              <Button size="small" icon={<SyncOutlined spin={backfilling} />} loading={backfilling} onClick={handleBackfill}>
                回填历史
              </Button>
            </Tooltip>
          </Col>
        </Row>
      </Card>
    )
  }

  const totals = summaryData?.totals || {}
  const items = summaryData?.items || []

  return (
    <div>
      <Title level={4}><KeyOutlined /> 关键词统计</Title>

      {autoExcludeSummary && autoExcludeSummary.total_excluded > 0 && (
        <Card
          size="small"
          style={{ marginBottom: 12, background: '#f6ffed', borderColor: '#b7eb8f' }}
          bodyStyle={{ padding: '10px 14px' }}
        >
          <Row align="middle" gutter={12}>
            <Col flex="auto">
              <Space size={8} wrap>
                <span style={{ fontSize: 18 }}>💰</span>
                <Text strong>屏蔽全店成果（最近 30 天）</Text>
                <Text>
                  共屏蔽 <Text strong style={{ color: '#cf1322' }}>{autoExcludeSummary.total_excluded}</Text> 个词
                  · 估算节省 <Text strong style={{ color: '#52c41a' }}>¥{autoExcludeSummary.total_saved_estimated.toLocaleString()}</Text>
                </Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  （自动托管 {autoExcludeSummary.auto_excluded ?? 0} · ¥{(autoExcludeSummary.auto_saved_estimated ?? 0).toLocaleString()}
                  ｜手动一键 {autoExcludeSummary.manual_excluded ?? 0} · ¥{(autoExcludeSummary.manual_saved_estimated ?? 0).toLocaleString()}）
                </Text>
              </Space>
            </Col>
            <Col flex="none">
              <Button size="small" type="link"
                onClick={() => setAutoExcludeExpand(v => !v)}>
                {autoExcludeExpand ? '收起' : '按活动展开 ▾'}
              </Button>
            </Col>
          </Row>
          {autoExcludeExpand && (autoExcludeSummary.by_campaign || []).length > 0 && (
            <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px dashed #d9f7be' }}>
              {autoExcludeSummary.by_campaign.map(c => (
                <Row key={c.campaign_id} style={{ padding: '4px 0', fontSize: 12 }}>
                  <Col flex="auto"><Text>{c.campaign_name}</Text></Col>
                  <Col flex="none">
                    <Space size={16}>
                      <Text type="secondary">{c.excluded_count} 个词</Text>
                      <Text strong style={{ color: '#52c41a' }}>¥{c.saved_estimated.toLocaleString()}</Text>
                    </Space>
                  </Col>
                </Row>
              ))}
            </div>
          )}
        </Card>
      )}

      {renderFilterBar()}

      <Spin spinning={loading}>
        {/* ② 汇总卡片 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          {[
            { title: '关键词数', value: totals.keywords, color: undefined },
            { title: '总曝光', value: totals.impressions, color: undefined },
            { title: '总点击', value: totals.clicks, color: undefined },
            { title: '平均 CTR', tip: '点击率 = 点击 ÷ 曝光 × 100%，反映广告吸引力', value: totals.avg_ctr, suffix: '%', color: '#1677ff' },
            { title: '总花费', value: totals.spend, suffix: '₽', color: '#722ed1' },
            { title: '平均 CPC', tip: '单次点击成本 = 花费 ÷ 点击数（₽），越低越好', value: totals.avg_cpc, suffix: '₽', color: '#fa8c16' },
          ].map((item, i) => (
            <Col xs={12} sm={8} md={4} key={i}>
              <Card size="small" bodyStyle={{ padding: 12 }}>
                <Statistic
                  title={item.tip ? (
                    <Tooltip title={item.tip}><span style={{ cursor: 'help' }}>{item.title} <span style={{ fontSize: 11, color: '#bbb' }}>ⓘ</span></span></Tooltip>
                  ) : item.title}
                  value={item.value ?? '-'}
                  suffix={item.suffix}
                  valueStyle={{ fontSize: 20, color: item.color }}
                />
              </Card>
            </Col>
          ))}
        </Row>

        {/* ③ 趋势图 */}
        <Card
          size="small"
          style={{ marginBottom: 16 }}
          title={`TOP 10 关键词${metricLabel[trendMetric]}趋势`}
          extra={
            <Radio.Group size="small" value={trendMetric} onChange={e => setTrendMetric(e.target.value)}>
              <Radio.Button value="impressions">曝光</Radio.Button>
              <Radio.Button value="clicks">点击</Radio.Button>
              <Radio.Button value="spend">花费</Radio.Button>
            </Radio.Group>
          }
        >
          {trendOption ? (
            <ReactECharts option={trendOption} style={{ height: 300 }} />
          ) : (
            <Empty description="暂无趋势数据" style={{ padding: 40 }} />
          )}
        </Card>

        {/* ④ 否定关键词建议 */}
        {negativeSugs.length > 0 && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message={`发现 ${negativeSugs.length} 个浪费词：花费高但几乎无点击`}
            description={
              <div style={{ marginTop: 8 }}>
                {negativeSugs.slice(0, 5).map((s, i) => (
                  <div key={i} style={{ fontSize: 12, marginBottom: 4 }}>
                    <Tag color="red">{s.keyword}</Tag>
                    <Text type="secondary">花费 {s.spend}₽，仅 {s.clicks} 次点击（CTR {s.ctr}%）</Text>
                  </div>
                ))}
                {negativeSugs.length > 5 && (
                  <Text type="secondary" style={{ fontSize: 12 }}>...及其他 {negativeSugs.length - 5} 个</Text>
                )}
              </div>
            }
          />
        )}

        {/* ⑤ 关键词明细表 */}
        <Card
          size="small"
          title={
            <Space>
              <Text strong>关键词明细</Text>
              <Text type="secondary" style={{ fontWeight: 400, fontSize: 13 }}>
                {summaryData?.date_from} ~ {summaryData?.date_to}
              </Text>
            </Space>
          }
          extra={
            <Space wrap>
              <Select
                size="small"
                style={{ width: 110 }}
                value={efficiencyFilter}
                onChange={v => { setEfficiencyFilter(v); setPage(1) }}
                options={EFFICIENCY_FILTER_OPTS}
              />
              <Select
                size="small"
                style={{ width: 110 }}
                value={`${sortBy}|${sortOrder}`}
                onChange={v => {
                  const [by, ord] = v.split('|')
                  setSortBy(by); setSortOrder(ord); setPage(1)
                }}
                options={SORT_OPTS}
              />
              <Button
                size="small"
                icon={<SettingOutlined />}
                onClick={() => setRulesDrawerOpen(true)}
              >
                效能规则
              </Button>
              <Select
                size="small"
                style={{ width: 140 }}
                placeholder="搜索关键词"
                allowClear
                showSearch
                value={keywordSearch || undefined}
                onChange={v => { setKeywordSearch(v || ''); setPage(1) }}
                onSearch={v => { setKeywordSearch(v || ''); setPage(1) }}
                open={false}
              />
              <Button size="small" icon={<DownloadOutlined />} disabled>导出 Excel</Button>
            </Space>
          }
        >
          <Table
            rowKey="keyword"
            size="middle"
            dataSource={items}
            columns={columns}
            loading={loading}
            pagination={{
              current: page,
              pageSize: 50,
              total: summaryData?.total || 0,
              showSizeChanger: false,
              showTotal: t => `共 ${t} 个关键词`,
              onChange: p => setPage(p),
            }}
            expandable={isOzon ? {
              expandedRowKeys: expandedKeys,
              onExpand: handleExpand,
              expandedRowRender: record => {
                const kw = record.keyword
                if (skuLoadingMap[kw]) return <div style={{ padding: 12, textAlign: 'center' }}>加载 SKU 明细...</div>
                const skus = skuDetailMap[kw]
                if (!skus || skus.length === 0) return (
                  <div style={{ padding: 12, background: '#fafafa', borderRadius: 4 }}>
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无 SKU 级明细" />
                  </div>
                )
                return (
                  <div style={{ padding: 8, background: '#fafafa', borderRadius: 4 }}>
                    <Text type="secondary" style={{ fontSize: 12, marginBottom: 8, display: 'block' }}>
                      该关键词在以下 {skus.length} 个商品上产生了流量：
                    </Text>
                    <Table
                      size="small"
                      rowKey="sku"
                      dataSource={skus}
                      pagination={false}
                      columns={[
                        { title: 'SKU', dataIndex: 'sku', width: 120 },
                        { title: '商品', dataIndex: 'title', ellipsis: true },
                        { title: '曝光', dataIndex: 'impressions', width: 80, render: v => v?.toLocaleString() },
                        { title: '点击', dataIndex: 'clicks', width: 70, render: v => v?.toLocaleString() },
                        { title: 'CTR', dataIndex: 'ctr', width: 70, render: v => `${v}%` },
                        { title: '花费', dataIndex: 'spend', width: 100, render: v => `${v?.toLocaleString()} ₽` },
                      ]}
                    />
                  </div>
                )
              },
              rowExpandable: () => true,
            } : undefined}
            locale={{
              emptyText: (
                <Empty
                  description={
                    syncStatus?.total_days
                      ? '该时间范围内无关键词数据'
                      : <span>尚未同步关键词数据，点击右上角 <Text strong>回填历史</Text> 开始</span>
                  }
                />
              ),
            }}
          />
        </Card>
      </Spin>

      {/* ==================== 关键词关联活动商品 Drawer ==================== */}
      <Drawer
        title={
          <Space size={8} wrap>
            <KeyOutlined />
            <span>关键词详情</span>
            <Tag>{kwDetailKeyword}</Tag>
            {kwTranslations[kwDetailKeyword] && kwTranslations[kwDetailKeyword] !== kwDetailKeyword && (
              <Tag color="blue">{kwTranslations[kwDetailKeyword]}</Tag>
            )}
            {(() => {
              const cfg = EFFICIENCY_MAP[kwDetailEfficiency] || EFFICIENCY_MAP.normal
              return <Tag color={cfg.color} icon={cfg.icon}>{cfg.label}</Tag>
            })()}
          </Space>
        }
        open={kwDetailDrawer}
        onClose={() => setKwDetailDrawer(false)}
        width="85%"
        destroyOnClose
      >
        {kwDetailLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin size="large" tip="加载中..." /></div>
        ) : kwDetailData ? (
          <div>
            {/* ===== 顶部汇总条 ===== */}
            {(() => {
              const camps = kwDetailData.campaigns || []
              const totalImp = camps.reduce((s, c) => s + (c.impressions || 0), 0)
              const totalClk = camps.reduce((s, c) => s + (c.clicks || 0), 0)
              const totalSp = camps.reduce((s, c) => s + (c.spend || 0), 0)
              const earliest = camps.map(c => c.keyword_first_seen).filter(Boolean).sort()[0]
              return (
                <div style={{
                  display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)',
                  gap: 12, marginBottom: 20,
                }}>
                  {[
                    { label: '涉及活动', value: camps.length, suffix: '个' },
                    { label: '总曝光', value: totalImp.toLocaleString() },
                    { label: '总点击', value: totalClk.toLocaleString() },
                    { label: '总花费', value: `${totalSp.toLocaleString()} ₽`, color: totalSp > 100 ? '#cf1322' : undefined },
                    { label: '首次出现', value: earliest || '-' },
                  ].map((item, i) => (
                    <div key={i} style={{
                      padding: '12px 14px', background: '#fafafa',
                      borderRadius: 8, borderLeft: `3px solid ${item.color || '#1677ff'}`,
                    }}>
                      <div style={{ fontSize: 12, color: '#888' }}>{item.label}</div>
                      <div style={{ fontSize: 20, fontWeight: 600, color: item.color || '#1f1f1f', marginTop: 2 }}>
                        {item.value}{item.suffix ? <span style={{ fontSize: 13, fontWeight: 400, marginLeft: 2 }}>{item.suffix}</span> : null}
                      </div>
                    </div>
                  ))}
                </div>
              )
            })()}

            {/* ===== 活动卡片列表 ===== */}
            {(kwDetailData.campaigns || []).map(camp => {
              const statusCfg = {
                active: { badge: 'success', text: '投放中', bg: '#f6ffed', border: '#b7eb8f' },
                paused: { badge: 'warning', text: '暂停', bg: '#fffbe6', border: '#ffe58f' },
                archived: { badge: 'default', text: '已归档', bg: '#f5f5f5', border: '#d9d9d9' },
              }[camp.status] || { badge: 'default', text: camp.status, bg: '#f5f5f5', border: '#d9d9d9' }
              const prods = camp.products?.length > 0 ? camp.products : camp.skus || []
              const excludedCount = prods.filter(p => p.is_excluded).length

              return (
                <Card key={camp.campaign_id} size="small"
                  style={{ marginBottom: 16, borderColor: statusCfg.border }}
                  styles={{ header: { background: statusCfg.bg, borderBottom: `1px solid ${statusCfg.border}` } }}
                  title={
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                        <Text strong style={{ fontSize: 14 }}>{camp.campaign_name}</Text>
                        <Badge status={statusCfg.badge} text={statusCfg.text} style={{ fontSize: 12 }} />
                      </div>
                      <div style={{ fontSize: 11, color: '#888', marginTop: 4 }}>
                        {camp.platform?.toUpperCase()} ID: {camp.platform_campaign_id}
                        {camp.keyword_first_seen && (
                          <span style={{ marginLeft: 12 }}>📅 首次出现: <b>{camp.keyword_first_seen}</b></span>
                        )}
                      </div>
                    </div>
                  }
                >
                  {/* 关键词数据卡片（活动级，WB API 不支持 SKU 级拆分） */}
                  <div style={{
                    display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)',
                    gap: 10, marginBottom: 14,
                  }}>
                    {[
                      { label: '曝光', value: camp.impressions?.toLocaleString(), icon: '👁' },
                      { label: '点击', value: camp.clicks?.toLocaleString(), icon: '👆' },
                      { label: '花费', value: `${camp.spend?.toLocaleString()} ₽`, icon: '💰',
                        color: camp.spend > 50 && camp.clicks < 3 ? '#cf1322' : undefined },
                      { label: 'CTR', value: `${camp.impressions > 0 ? (camp.clicks / camp.impressions * 100).toFixed(2) : 0}%`, icon: '📊' },
                      { label: '加入时间', value: camp.keyword_first_seen || '-', icon: '📅' },
                    ].map((item, i) => (
                      <div key={i} style={{
                        padding: '8px 10px', background: '#fafafa',
                        borderRadius: 6, textAlign: 'center',
                      }}>
                        <div style={{ fontSize: 11, color: '#888' }}>{item.icon} {item.label}</div>
                        <div style={{ fontSize: 16, fontWeight: 600, color: item.color || '#1f1f1f', marginTop: 2 }}>
                          {item.value}
                        </div>
                      </div>
                    ))}
                  </div>

                  <div style={{ fontSize: 11, color: '#999', marginBottom: 10, fontStyle: 'italic' }}>
                    ⚠ 以上为该关键词在整个活动中的数据。WB API 不支持按单个商品拆分关键词统计，屏蔽操作按商品执行。
                  </div>

                  {/* 商品列表 */}
                  {prods.length > 0 ? (
                    <div>
                      <div style={{
                        fontSize: 12, color: '#666', marginBottom: 8,
                        display: 'flex', justifyContent: 'space-between',
                      }}>
                        <span>
                          <StopOutlined style={{ marginRight: 4 }} />
                          选择要屏蔽此关键词的商品
                        </span>
                        <span style={{ color: '#888' }}>
                          {prods.length} 个商品 · {excludedCount} 个已屏蔽
                        </span>
                      </div>
                      <div style={{
                        border: '1px solid #f0f0f0', borderRadius: 8,
                        overflow: 'hidden',
                      }}>
                        {prods.map((p, idx) => {
                          const nmId = p.nm_id || parseInt(p.sku || '0')
                          const name = p.name || p.subject_name || ''
                          const excKey = `${camp.campaign_id}:${nmId}`
                          const isExcluded = p.is_excluded
                          return (
                            <div key={nmId} style={{
                              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                              padding: '8px 12px',
                              background: isExcluded ? '#fafafa' : (idx % 2 === 0 ? '#fff' : '#fafcff'),
                              borderBottom: idx < prods.length - 1 ? '1px solid #f5f5f5' : 'none',
                              opacity: isExcluded ? 0.5 : 1,
                            }}>
                              <div style={{ flex: 1 }}>
                                <div>
                                  <Text style={{ fontSize: 13, fontWeight: 500 }}>商品ID: {nmId}</Text>
                                  {p.sku && (
                                    <Text style={{ marginLeft: 10, fontSize: 12, color: '#1677ff' }}>SKU: {p.sku}</Text>
                                  )}
                                </div>
                                <div style={{ fontSize: 11, color: '#888', marginTop: 1 }}>
                                  {p.name_zh && <span style={{ color: '#333', marginRight: 8 }}>{p.name_zh}</span>}
                                  {name && <span>{name}</span>}
                                </div>
                              </div>
                              <Space size={6}>
                                {!isExcluded && kwDetailEfficiency === 'waste' && (
                                  <Tag color="red" style={{ margin: 0, fontSize: 10, lineHeight: '16px' }}>浪费词，建议屏蔽</Tag>
                                )}
                                {!isExcluded && kwDetailEfficiency === 'star' && (
                                  <Tag color="green" style={{ margin: 0, fontSize: 10, lineHeight: '16px' }}>高效词</Tag>
                                )}
                                {!isExcluded && kwDetailEfficiency === 'potential' && (
                                  <Tag color="blue" style={{ margin: 0, fontSize: 10, lineHeight: '16px' }}>潜力词</Tag>
                                )}
                                {isExcluded ? (
                                  <Tag color="default" style={{ margin: 0, fontSize: 11 }}>✓ 已屏蔽</Tag>
                                ) : (
                                  <Popconfirm
                                    title={`对商品 ${nmId} 屏蔽此关键词？`}
                                    description={`屏蔽「${kwDetailKeyword}」后该商品不再因此词展示广告`}
                                    okText="确认屏蔽"
                                    cancelText="取消"
                                    onConfirm={() => handleExcludeKeyword(camp.campaign_id, nmId, kwDetailKeyword)}
                                  >
                                    <Button size="small" danger icon={<StopOutlined />}
                                      loading={excluding === excKey}
                                      style={{ fontSize: 12 }}>
                                      屏蔽
                                    </Button>
                                  </Popconfirm>
                                )}
                              </Space>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  ) : (
                    <Empty description="暂无商品数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                  )}
                </Card>
              )
            })}
          </div>
        ) : (
          <Empty description="无关联数据" />
        )}
      </Drawer>

      <EfficiencyRulesDrawer
        open={rulesDrawerOpen}
        onClose={() => setRulesDrawerOpen(false)}
        onSaved={() => { if (searched) fetchAll() }}
      />
    </div>
  )
}

export default KeywordStats
