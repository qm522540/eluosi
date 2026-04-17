import { useState, useEffect, useCallback } from 'react'
import {
  Typography, Card, Table, Button, Space, Select, Row, Col, Statistic, Tag,
  Empty, Spin, Alert, message, Tooltip, DatePicker, Radio, Segmented, Badge,
  Drawer, Popconfirm,
} from 'antd'
import {
  KeyOutlined, DownloadOutlined, ReloadOutlined, SyncOutlined,
  StarFilled, BulbOutlined, WarningFilled, SearchOutlined,
  StopOutlined, EyeOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import { getShops } from '@/api/shops'
import {
  getKeywordSummary, getKeywordTrend, getKeywordSkuDetail,
  getNegativeSuggestions, getKeywordSyncStatus, backfillKeywords,
  translateKeywords, getKeywordCampaigns, excludeKeyword,
} from '@/api/keyword_stats'

const { Title, Text } = Typography
const { Option } = Select

const PLATFORM_LABEL = { wb: 'WB', ozon: 'Ozon', yandex: 'YM' }

const EFFICIENCY_MAP = {
  star: { color: 'green', icon: <StarFilled />, label: '高效词', tip: '点击率 ≥ 5% 且单次点击成本低于平均值，性价比高的好词' },
  potential: { color: 'blue', icon: <BulbOutlined />, label: '潜力词', tip: '点击率 ≥ 3% 但曝光偏少，有潜力但需要更多预算曝光' },
  waste: { color: 'red', icon: <WarningFilled />, label: '浪费词', tip: '点击率 < 1% 但花费高于平均值，钱花了没效果，建议屏蔽' },
  normal: { color: 'default', icon: null, label: '普通', tip: '表现一般，暂不需要特殊处理' },
}

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
  const [kwDetailData, setKwDetailData] = useState(null)
  const [kwDetailLoading, setKwDetailLoading] = useState(false)
  const [excluding, setExcluding] = useState(null) // campaign_id:nm_id being excluded
  const [syncStatus, setSyncStatus] = useState(null)
  const [page, setPage] = useState(1)
  const [sortBy, setSortBy] = useState('spend')
  const [keywordSearch, setKeywordSearch] = useState('')

  // SKU 展开
  const [expandedKeys, setExpandedKeys] = useState([])
  const [skuDetailMap, setSkuDetailMap] = useState({})
  const [skuLoadingMap, setSkuLoadingMap] = useState({})

  // 初始化/回填
  const [backfilling, setBackfilling] = useState(false)

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
        getKeywordSummary({ shop_id: shopId, ...range, sort_by: sortBy, page, size: 50, keyword: keywordSearch || undefined }),
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
  }, [shopId, getDateRange, sortBy, page, trendMetric, keywordSearch])

  useEffect(() => {
    if (searched) fetchAll()
  }, [searched, fetchAll])

  const handleViewKeywordCampaigns = async (keyword) => {
    setKwDetailKeyword(keyword)
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
      render: (v) => {
        const zh = kwTranslations[v]
        return (
          <Space size={6}>
            <Tooltip title={zh && zh !== v ? `中文：${zh}` : '翻译加载中...'}>
              <Text strong style={{ fontSize: 13, cursor: 'help' }}>{v}</Text>
            </Tooltip>
            <Tooltip title="查看引用此关键词的活动和商品">
              <Button size="small" type="text" icon={<EyeOutlined />}
                style={{ fontSize: 11, padding: '0 4px', height: 20 }}
                onClick={() => handleViewKeywordCampaigns(v)} />
            </Tooltip>
          </Space>
        )
      },
    },
    {
      title: '效能', dataIndex: 'efficiency', key: 'efficiency', width: 100,
      filters: [
        { text: '高效词', value: 'star' },
        { text: '潜力词', value: 'potential' },
        { text: '浪费词', value: 'waste' },
        { text: '普通', value: 'normal' },
      ],
      onFilter: (val, record) => record.efficiency === val,
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
      title: <Tooltip title="广告被展示给用户的次数"><span style={{ cursor: 'help' }}>曝光 <span style={{ fontSize: 10, color: '#bbb' }}>ⓘ</span></span></Tooltip>,
      dataIndex: 'impressions', key: 'impressions', width: 100,
      sorter: (a, b) => a.impressions - b.impressions,
      render: v => v?.toLocaleString(),
    },
    {
      title: <Tooltip title="用户看到广告后点击进入商品页的次数"><span style={{ cursor: 'help' }}>点击 <span style={{ fontSize: 10, color: '#bbb' }}>ⓘ</span></span></Tooltip>,
      dataIndex: 'clicks', key: 'clicks', width: 80,
      sorter: (a, b) => a.clicks - b.clicks,
      render: v => v?.toLocaleString(),
    },
    {
      title: <Tooltip title="点击率 = 点击 ÷ 曝光 × 100%，反映广告吸引力"><span style={{ cursor: 'help' }}>CTR <span style={{ fontSize: 10, color: '#bbb' }}>ⓘ</span></span></Tooltip>,
      dataIndex: 'ctr', key: 'ctr', width: 80,
      sorter: (a, b) => a.ctr - b.ctr,
      render: v => v != null ? `${v}%` : '-',
    },
    {
      title: <Tooltip title="该关键词在选定日期范围内的广告总花费"><span style={{ cursor: 'help' }}>花费 <span style={{ fontSize: 10, color: '#bbb' }}>ⓘ</span></span></Tooltip>,
      dataIndex: 'spend', key: 'spend', width: 110,
      sorter: (a, b) => a.spend - b.spend,
      defaultSortOrder: 'descend',
      render: v => v != null ? <Text strong>{v.toLocaleString()} ₽</Text> : '-',
    },
    {
      title: <Tooltip title="单次点击成本 = 花费 ÷ 点击数，越低越好"><span style={{ cursor: 'help' }}>CPC <span style={{ fontSize: 10, color: '#bbb' }}>ⓘ</span></span></Tooltip>,
      dataIndex: 'cpc', key: 'cpc', width: 80,
      sorter: (a, b) => a.cpc - b.cpc,
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
            <Space>
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
          <Space>
            <KeyOutlined />
            <span>关键词详情</span>
            <Tag>{kwDetailKeyword}</Tag>
            {kwTranslations[kwDetailKeyword] && kwTranslations[kwDetailKeyword] !== kwDetailKeyword && (
              <Tag color="blue">{kwTranslations[kwDetailKeyword]}</Tag>
            )}
          </Space>
        }
        open={kwDetailDrawer}
        onClose={() => setKwDetailDrawer(false)}
        width="85%"
        destroyOnClose
      >
        {kwDetailLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
        ) : kwDetailData ? (
          <div>
            <div style={{ fontSize: 13, color: '#666', marginBottom: 16 }}>
              共在 {kwDetailData.campaigns?.length || 0} 个活动中出现
            </div>
            {(kwDetailData.campaigns || []).map(camp => (
              <Card key={camp.campaign_id} size="small" style={{ marginBottom: 12 }}
                title={
                  <Space size={8} wrap>
                    <span>{camp.campaign_name}</span>
                    <Badge
                      status={camp.status === 'active' ? 'success' : camp.status === 'paused' ? 'warning' : 'default'}
                      text={camp.status === 'active' ? '投放中' : camp.status === 'paused' ? '暂停' : camp.status === 'archived' ? '已归档' : camp.status}
                      style={{ fontSize: 12 }}
                    />
                    <Tag color="default" style={{ fontSize: 10 }}>
                      {camp.platform?.toUpperCase()} ID: {camp.platform_campaign_id}
                    </Tag>
                    {camp.keyword_first_seen && (
                      <Tooltip title="该关键词在此活动中首次出现数据的日期">
                        <Tag color="blue" style={{ fontSize: 10, margin: 0 }}>
                          首次出现: {camp.keyword_first_seen}
                        </Tag>
                      </Tooltip>
                    )}
                  </Space>
                }
              >
                <Row gutter={16} style={{ marginBottom: 10 }}>
                  <Col span={6}><Text type="secondary">关键词曝光</Text><br/><Text strong>{camp.impressions?.toLocaleString()}</Text></Col>
                  <Col span={6}><Text type="secondary">关键词点击</Text><br/><Text strong>{camp.clicks?.toLocaleString()}</Text></Col>
                  <Col span={6}><Text type="secondary">关键词花费</Text><br/><Text strong>{camp.spend?.toLocaleString()} ₽</Text></Col>
                  <Col span={6}><Text type="secondary">CTR</Text><br/><Text strong>{camp.impressions > 0 ? (camp.clicks / camp.impressions * 100).toFixed(2) : 0}%</Text></Col>
                </Row>
                {/* 活动下的商品列表（屏蔽时选对哪个商品操作） */}
                {(camp.products?.length > 0 || camp.skus?.length > 0) ? (
                  <div>
                    <div style={{
                      padding: '8px 10px', marginBottom: 8,
                      background: '#f6f8ff', border: '1px solid #e6edff',
                      borderRadius: 6, fontSize: 12,
                    }}>
                      <div style={{ fontWeight: 500, color: '#333', marginBottom: 4 }}>
                        该关键词在此活动中的数据
                      </div>
                      <Space size={16}>
                        <span>曝光 <b>{camp.impressions?.toLocaleString()}</b></span>
                        <span>点击 <b>{camp.clicks?.toLocaleString()}</b></span>
                        <span>花费 <b>{camp.spend?.toLocaleString()}₽</b></span>
                        <span>CTR <b>{camp.impressions > 0 ? (camp.clicks / camp.impressions * 100).toFixed(2) : 0}%</b></span>
                        {camp.keyword_first_seen && (
                          <span>加入时间 <b>{camp.keyword_first_seen}</b></span>
                        )}
                      </Space>
                    </div>
                    <div style={{ fontSize: 12, color: '#888', marginBottom: 6 }}>
                      选择要屏蔽此关键词的商品（{(camp.products || camp.skus || []).length} 个）
                    </div>
                    {/* 优先展示 products（有 nm_id + 名称），fallback 到 skus */}
                    {(camp.products?.length > 0 ? camp.products : camp.skus || []).map(p => {
                      const nmId = p.nm_id || parseInt(p.sku || '0')
                      const name = p.name || p.subject_name || `商品 ${nmId}`
                      const excKey = `${camp.campaign_id}:${nmId}`
                      const isExcluded = p.is_excluded
                      return (
                        <div key={nmId} style={{
                          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                          padding: '6px 0', borderBottom: '1px solid #f5f5f5',
                          opacity: isExcluded ? 0.6 : 1,
                        }}>
                          <div style={{ flex: 1 }}>
                            <Text style={{ fontSize: 12, fontWeight: 500 }}>nm_id: {nmId}</Text>
                            {name && <Text style={{ marginLeft: 8, fontSize: 11, color: '#888' }}>{name}</Text>}
                          </div>
                          {isExcluded ? (
                            <Tag color="default" style={{ margin: 0 }}>已屏蔽</Tag>
                          ) : (
                            <Popconfirm
                              title={`对商品 ${nmId} 屏蔽「${kwDetailKeyword}」？`}
                              description="屏蔽后该商品不再因此关键词展示广告"
                              onConfirm={() => handleExcludeKeyword(camp.campaign_id, nmId, kwDetailKeyword)}
                            >
                              <Button size="small" danger icon={<StopOutlined />}
                                loading={excluding === excKey}>
                                屏蔽
                              </Button>
                            </Popconfirm>
                          )}
                        </div>
                      )
                    })}
                  </div>
                ) : (
                  <div style={{ fontSize: 12, color: '#888' }}>
                    暂无商品数据
                  </div>
                )}
              </Card>
            ))}
          </div>
        ) : (
          <Empty description="无关联数据" />
        )}
      </Drawer>
    </div>
  )
}

export default KeywordStats
