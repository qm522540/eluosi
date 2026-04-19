import { useState, useEffect, useCallback } from 'react'
import {
  Typography, Card, Table, Button, Tag, Space, Select, Row, Col,
  Statistic, Modal, Form, Input, InputNumber, message, DatePicker, Tooltip, Badge, Empty,
  Popconfirm, Tabs, Alert, Drawer, Descriptions, List, Divider, Progress, Checkbox, Popover,
  Switch, Segmented, Spin, notification,
} from 'antd'
import {
  SearchOutlined, EditOutlined, EyeOutlined, SyncOutlined, PlusOutlined,
  DeleteOutlined, SettingOutlined, ExclamationCircleOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import { formatMoscowTime } from '@/utils/time'
import WbProductImg from '@/components/WbProductImg'
import {
  getCampaigns, getCampaign, createCampaign, updateCampaign, deleteCampaign,
  getAdGroups, createAdGroup, updateAdGroup, deleteAdGroup,
  getKeywords, createKeyword, batchCreateKeywords, updateKeyword, deleteKeyword,
  getAdStats, getAdSummary,
  exportAdStats, getAlerts, getAlertConfig, updateAlertConfig,
  getCampaignProducts, getCampaignKeywords, excludeKeywords, updateCampaignBid, getCampaignBudget,
  addProtectedKeyword, removeProtectedKeyword,
  getAutoExcludeConfig, toggleAutoExclude, runAutoExcludeNow, getAutoExcludeLogs,
  getCampaignSummary, getOzonSkuQueries, syncOzonSkuQueries,
  getTodaySummaryByCampaign, getTodaySummaryByShop, getTodayAlertsByShop,
} from '@/api/ads'
import { getListings } from '@/api/products'
import { getEfficiencyRules } from '@/api/keyword_stats'
import EfficiencyRulesDrawer from '@/pages/reports/EfficiencyRulesDrawer'
import { PLATFORMS, AD_STATUS, AD_TYPES } from '@/utils/constants'

const { Title, Text } = Typography
const { RangePicker } = DatePicker
const { TextArea } = Input

const MATCH_TYPES = {
  exact: '精确匹配',
  phrase: '短语匹配',
  broad: '广泛匹配',
}

// ==================== 列选择器 ====================

const ColumnSelector = ({ platform, allColumns, visibleColumns, defaultColumns, onChange }) => {
  const groups = {}
  Object.entries(allColumns).forEach(([key, col]) => {
    if (col.fixed) return
    if (col.platforms && !col.platforms.includes(platform)) return
    const group = col.group || '其他'
    if (!groups[group]) groups[group] = []
    groups[group].push({ key, ...col })
  })

  const content = (
    <div style={{ width: 280 }}>
      {Object.entries(groups).map(([group, cols]) => (
        <div key={group} style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 12, color: '#999', marginBottom: 6, fontWeight: 500 }}>{group}</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
            {cols.map(col => (
              <Checkbox
                key={col.key}
                checked={visibleColumns.includes(col.key)}
                onChange={e => {
                  if (e.target.checked) onChange([...visibleColumns, col.key])
                  else onChange(visibleColumns.filter(k => k !== col.key))
                }}
              >
                <span style={{ fontSize: 13 }}>{col.title}</span>
              </Checkbox>
            ))}
          </div>
        </div>
      ))}
      <div style={{ borderTop: '1px solid #f0f0f0', paddingTop: 8, marginTop: 4 }}>
        <Button size="small" type="link" onClick={() => onChange(defaultColumns[platform] || [])}>恢复默认</Button>
      </div>
    </div>
  )

  return (
    <Popover content={content} title="自定义显示列" trigger="click" placement="bottomRight">
      <Button size="small" icon={<SettingOutlined />}>自定义列</Button>
    </Popover>
  )
}

// ==================== 汇总卡片 ====================

const TodaySummaryBar = ({ shopId }) => {
  const [summary, setSummary] = useState(null)
  const [alerts, setAlerts] = useState(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async (refresh = false) => {
    if (!shopId) { setSummary(null); setAlerts(null); return }
    setLoading(true)
    try {
      const [s, a] = await Promise.all([
        getTodaySummaryByShop(shopId, refresh),
        getTodayAlertsByShop(shopId),
      ])
      setSummary(s.data)
      setAlerts(a.data)
    } catch {
      setSummary(null); setAlerts(null)
    } finally { setLoading(false) }
  }, [shopId])

  useEffect(() => { load() }, [load])

  if (!shopId) return null

  return (
    <>
      <Card
        size="small"
        style={{ marginBottom: 12, background: '#fafbff', borderColor: '#e6edff' }}
        bodyStyle={{ padding: '10px 14px' }}
      >
        <Spin spinning={loading}>
          <Row gutter={16} align="middle" wrap={false}>
            <Col flex="none">
              <Space size={6}>
                <Text strong style={{ fontSize: 13 }}>今日</Text>
                <Tooltip title="WB 数据有几小时延迟，早上常空，下午陆续就位。聚合店铺下所有 active 活动。">
                  <Text type="secondary" style={{ fontSize: 11, cursor: 'help' }}>
                    {summary?.today_date || '-'}
                    {summary?.active_campaign_count != null
                      ? ` · ${summary.active_campaign_count} 活动` : ''}
                  </Text>
                </Tooltip>
              </Space>
            </Col>
            <Col flex="auto">
              <Row gutter={16}>
                <Col span={4}>
                  <div style={{ fontSize: 11, color: '#999' }}>花费</div>
                  <div style={{ fontSize: 16, fontWeight: 600 }}>
                    ₽{(summary?.spend ?? 0).toLocaleString()}
                  </div>
                </Col>
                <Col span={4}>
                  <div style={{ fontSize: 11, color: '#999' }}>订单</div>
                  <div style={{ fontSize: 16, fontWeight: 600, color: '#52c41a' }}>
                    {summary?.orders ?? 0}
                  </div>
                </Col>
                <Col span={4}>
                  <div style={{ fontSize: 11, color: '#999' }}>曝光</div>
                  <div style={{ fontSize: 16, fontWeight: 600 }}>
                    {(summary?.views ?? 0).toLocaleString()}
                  </div>
                </Col>
                <Col span={4}>
                  <div style={{ fontSize: 11, color: '#999' }}>点击</div>
                  <div style={{ fontSize: 16, fontWeight: 600 }}>
                    {summary?.clicks ?? 0}
                  </div>
                </Col>
                <Col span={4}>
                  <div style={{ fontSize: 11, color: '#999' }}>CTR</div>
                  <div style={{ fontSize: 16, fontWeight: 600 }}>
                    {summary?.ctr ? `${summary.ctr}%` : '-'}
                  </div>
                </Col>
                <Col span={4}>
                  <div style={{ fontSize: 11, color: '#999' }}>ROAS</div>
                  <div style={{
                    fontSize: 16, fontWeight: 600,
                    color: (summary?.roas ?? 0) >= 2 ? '#52c41a'
                         : (summary?.roas ?? 0) > 0 ? '#faad14' : '#999',
                  }}>
                    {summary?.roas ? `${summary.roas}x` : '-'}
                  </div>
                </Col>
              </Row>
            </Col>
            <Col flex="none">
              <Button size="small" icon={<SyncOutlined spin={loading} />}
                onClick={() => load(true)}>刷新</Button>
            </Col>
          </Row>
        </Spin>
      </Card>

      {/* 异常告警条 */}
      {alerts && alerts.alert_count > 0 && (
        <Card
          size="small"
          style={{ marginBottom: 12, background: '#fff', borderColor: '#ffccc7' }}
          bodyStyle={{ padding: '10px 14px' }}
        >
          <div style={{ marginBottom: 6 }}>
            <Text strong style={{ fontSize: 12, color: '#cf1322' }}>
              ⚠ 今日异常 {alerts.alert_count} 项（共扫 {alerts.checked_count} 个活动）
            </Text>
          </div>
          <Space direction="vertical" size={4} style={{ width: '100%' }}>
            {alerts.alerts.slice(0, 8).map((a, i) => {
              const tagColor = a.severity === 'high' ? 'red' : 'orange'
              const tagText = a.type === 'zero_order_waste' ? '烧钱无单'
                : a.type === 'low_roas' ? 'ROAS 低'
                : a.type === 'low_budget' ? '预算低' : '异常'
              return (
                <div key={i} style={{ fontSize: 12, display: 'flex', gap: 8, alignItems: 'center' }}>
                  <Tag color={tagColor} style={{ margin: 0, fontSize: 11 }}>{tagText}</Tag>
                  <Text strong style={{ fontSize: 12 }}>{a.campaign_name}</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>{a.msg}</Text>
                </div>
              )
            })}
            {alerts.alerts.length > 8 && (
              <Text type="secondary" style={{ fontSize: 11 }}>
                还有 {alerts.alerts.length - 8} 项，未列出
              </Text>
            )}
          </Space>
        </Card>
      )}
    </>
  )
}

// ==================== 主组件 ====================

const AdsOverview = ({ shopId, platform, shops, searched, syncing, lastSyncTime, onSync }) => {
  // 汇总数据
  const [summary, setSummary] = useState(null)
  const [summaryLoading, setSummaryLoading] = useState(false)

  // 活动列表
  const [campaigns, setCampaigns] = useState([])
  const [listLoading, setListLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [filterStatus, setFilterStatus] = useState(null)

  // 编辑弹窗
  const [editVisible, setEditVisible] = useState(false)
  const [editingCampaign, setEditingCampaign] = useState(null)
  const [editSubmitting, setEditSubmitting] = useState(false)
  const [editForm] = Form.useForm()

  // 创建活动弹窗
  const [createVisible, setCreateVisible] = useState(false)
  const [createSubmitting, setCreateSubmitting] = useState(false)
  const [createForm] = Form.useForm()

  // 同步状态
  // syncing 从 props 传入（父组件管理同步状态）

  // 详情抽屉
  const [detailVisible, setDetailVisible] = useState(false)
  const [detailData, setDetailData] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  // 活动汇总指标（基本信息页用）
  const [campaignSummaryData, setCampaignSummaryData] = useState(null)
  const [campaignSummaryLoading, setCampaignSummaryLoading] = useState(false)
  const [summaryDays, setSummaryDays] = useState(7)
  // 活动级自动屏蔽托管
  const [autoExcludeCfg, setAutoExcludeCfg] = useState(null)
  const [autoExcludeBusy, setAutoExcludeBusy] = useState(false)
  const [autoExcludeLogsDrawer, setAutoExcludeLogsDrawer] = useState(false)
  const [autoExcludeLogs, setAutoExcludeLogs] = useState([])
  const [autoExcludeLogsLoading, setAutoExcludeLogsLoading] = useState(false)
  const [detailTab, setDetailTab] = useState('info')

  // 广告组
  const [adGroups, setAdGroups] = useState([])
  const [groupsLoading, setGroupsLoading] = useState(false)
  const [groupFormVisible, setGroupFormVisible] = useState(false)
  const [editingGroup, setEditingGroup] = useState(null)
  const [groupForm] = Form.useForm()
  const [groupSubmitting, setGroupSubmitting] = useState(false)

  // 关键词
  const [keywords, setKeywords] = useState([])
  const [keywordsLoading, setKeywordsLoading] = useState(false)
  const [selectedGroupId, setSelectedGroupId] = useState(null)
  const [kwFormVisible, setKwFormVisible] = useState(false)
  const [kwBatchVisible, setKwBatchVisible] = useState(false)
  const [editingKeyword, setEditingKeyword] = useState(null)
  const [kwForm] = Form.useForm()
  const [kwBatchForm] = Form.useForm()
  const [kwSubmitting, setKwSubmitting] = useState(false)

  // 统计图表
  const [statsData, setStatsData] = useState([])
  const [statsLoading, setStatsLoading] = useState(false)
  const [dateRange, setDateRange] = useState([dayjs().subtract(6, 'day'), dayjs()])

  // ROI告警
  const [alertsVisible, setAlertsVisible] = useState(false)
  const [alerts, setAlerts] = useState([])
  const [alertsLoading, setAlertsLoading] = useState(false)
  const [alertsTotal, setAlertsTotal] = useState(0)
  const [alertsPage, setAlertsPage] = useState(1)

  // 告警配置
  const [configVisible, setConfigVisible] = useState(false)
  const [alertConfig, setAlertConfig] = useState(null)
  const [configForm] = Form.useForm()
  const [configSubmitting, setConfigSubmitting] = useState(false)

  // 导出
  const [exporting, setExporting] = useState(false)

  // 活动详情增强：预算 + 商品
  const [campaignBudget, setCampaignBudget] = useState(null)
  const [campaignProducts, setCampaignProducts] = useState([])
  const [productsLoading, setProductsLoading] = useState(false)
  const [editingBid, setEditingBid] = useState(null)
  const [newBidValue, setNewBidValue] = useState(null)
  const [bidUpdating, setBidUpdating] = useState(false)

  // 商品 → 广告组 → 关键词链路
  // listings 用于把 campaignProducts.sku(=platform_product_id) 映射到本地 listing_id
  const [shopListings, setShopListings] = useState([])
  // 行展开：sku → keyword[] 缓存；loading 集合防重复请求
  const [expandedSkuKeys, setExpandedSkuKeys] = useState([])
  const [keywordsBySku, setKeywordsBySku] = useState({})
  const [keywordsLoadingSku, setKeywordsLoadingSku] = useState({})
  // 屏蔽规则：复用关键词效能规则（租户级，跟"关键词明细→效能规则"共用同一份）
  // 判定为"建议屏蔽"必须同时满足：观察 ≥ waste_min_days + 曝光 ≥ min_impressions
  //                                + CTR ≤ waste_ctr_max + 花费 ≥ 平均×waste_spend_min_ratio
  const [excludeRules, setExcludeRules] = useState(null)
  const [rulesDrawerOpen, setRulesDrawerOpen] = useState(false)
  const [excludingKws, setExcludingKws] = useState(false)
  const [qualityCheckedSku, setQualityCheckedSku] = useState(null)  // 当前质检的 SKU
  const [suggestedExcludeWords, setSuggestedExcludeWords] = useState([])  // 质检标出的词
  const [kwTablePageMap, setKwTablePageMap] = useState({})  // 每个 SKU 关键词表的当前页

  // 当日实时汇总（活动级，商品出价 Tab 顶部条）
  const [todaySummary, setTodaySummary] = useState(null)
  const [todayLoading, setTodayLoading] = useState(false)
  const loadTodaySummary = useCallback(async (cId, refresh = false) => {
    if (!cId) return
    setTodayLoading(true)
    try {
      const r = await getTodaySummaryByCampaign(cId, refresh)
      setTodaySummary(r.data || null)
    } catch {
      setTodaySummary(null)
    } finally {
      setTodayLoading(false)
    }
  }, [])

  const loadExcludeRules = useCallback(async () => {
    try {
      const r = await getEfficiencyRules()
      setExcludeRules(r.data?.rules || null)
    } catch {
      setExcludeRules(null)  // 兜底走 DEFAULT_RULES
    }
  }, [])
  useEffect(() => { loadExcludeRules() }, [loadExcludeRules])

  // WB API 限制：屏蔽词只支持单个词（不接受含空格短语）。含空格的搜索词
  // 是 WB 系统返回的"用户实际搜索短语"，无法通过 set-minus 接口屏蔽
  const isPhraseUnsupported = (kw) => (kw.keyword || '').trim().includes(' ')

  // 按规则筛选"建议屏蔽"关键词（waste 判定 + 观察天数门槛 + 跳过白名单 + 跳过短语）
  const getSuggestedExcludes = (kws) => {
    if (!kws || !kws.length) return []
    const r = excludeRules || {}
    const minDays = r.waste_min_days ?? 5
    const minImp = r.min_impressions ?? 20
    const ctrMax = r.waste_ctr_max ?? 1.0
    const spendRatio = r.waste_spend_min_ratio ?? 1.0
    // 当前 SKU 关键词集合的平均花费（参与判定的基准）
    const candidates = kws.filter(kw => !kw.is_excluded && !kw.is_protected && !isPhraseUnsupported(kw))
    const avgSpend = candidates.length
      ? candidates.reduce((s, k) => s + (k.sum || 0), 0) / candidates.length
      : 0
    return candidates.filter(kw => {
      if ((kw.active_days || 0) < minDays) return false
      if ((kw.views || 0) < minImp) return false
      const ctr = kw.views > 0 ? (kw.clicks / kw.views * 100) : 0
      if (ctr > ctrMax) return false
      if (avgSpend <= 0 || (kw.sum || 0) < avgSpend * spendRatio) return false
      return true
    })
  }

  // ==================== 活动级自动屏蔽托管 ====================

  const handleToggleAutoExclude = async (checked) => {
    if (!detailData?.id) return
    setAutoExcludeBusy(true)
    try {
      await toggleAutoExclude(detailData.id, checked)
      const r = await getAutoExcludeConfig(detailData.id)
      setAutoExcludeCfg(r.data)
      message.success(checked ? '已开启：明天凌晨自动屏蔽' : '已关闭')
    } catch (err) {
      message.error(err.message || '操作失败')
    } finally {
      setAutoExcludeBusy(false)
    }
  }

  const handleRunAutoExcludeNow = async () => {
    if (!detailData?.id) return
    setAutoExcludeBusy(true)
    try {
      const r = await runAutoExcludeNow(detailData.id)
      const d = r.data || {}
      message.success(
        `本次屏蔽 ${d.excluded || 0} 个词，估算月省 ¥${(d.estimated_saved_per_month || 0).toLocaleString()}`,
        4,
      )
      const cfg = await getAutoExcludeConfig(detailData.id)
      setAutoExcludeCfg(cfg.data)
    } catch (err) {
      message.error(err.message || err?.response?.data?.msg || '运行失败')
    } finally {
      setAutoExcludeBusy(false)
    }
  }

  const reloadCampaignSummary = async (days) => {
    if (!detailData?.id || detailData.platform !== 'wb') return
    setSummaryDays(days)
    setCampaignSummaryLoading(true)
    try {
      const r = await getCampaignSummary(detailData.id, days)
      setCampaignSummaryData(r.data)
    } catch {
      setCampaignSummaryData(null)
    } finally {
      setCampaignSummaryLoading(false)
    }
  }

  // 懒加载：用户切到「基本信息」Tab 才拉 campaign summary（避免 WB 限速）
  useEffect(() => {
    if (detailVisible && detailTab === 'info' && detailData?.platform === 'wb'
        && detailData?.id && !campaignSummaryData && !campaignSummaryLoading) {
      reloadCampaignSummary(summaryDays)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detailVisible, detailTab, detailData?.id])

  // 切到商品出价 Tab → 拉今日实时汇总（5 分钟缓存，反复切不会反复打 WB）
  useEffect(() => {
    if (detailVisible && detailTab === 'products' && detailData?.id) {
      loadTodaySummary(detailData.id)
    } else if (!detailVisible) {
      setTodaySummary(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detailVisible, detailTab, detailData?.id])

  const handleViewAutoExcludeLogs = async () => {
    if (!detailData?.id) return
    setAutoExcludeLogsDrawer(true)
    setAutoExcludeLogsLoading(true)
    try {
      const r = await getAutoExcludeLogs(detailData.id, 30)
      setAutoExcludeLogs(r.data?.items || [])
    } catch {
      setAutoExcludeLogs([])
    } finally {
      setAutoExcludeLogsLoading(false)
    }
  }

  // 切换关键词的"智能屏蔽白名单"标记（A 粒度: campaign + nm_id + keyword）
  const toggleProtected = async (sku, keyword, currentProtected) => {
    if (!detailData?.id) return
    const nmId = parseInt(sku)
    try {
      if (currentProtected) {
        await removeProtectedKeyword(detailData.id, nmId, keyword)
      } else {
        await addProtectedKeyword(detailData.id, nmId, keyword)
      }
      // 乐观更新本地缓存：把对应 keyword 的 is_protected 翻转
      setKeywordsBySku(m => {
        const list = m[sku] || []
        return {
          ...m,
          [sku]: list.map(kw =>
            kw.keyword === keyword ? { ...kw, is_protected: !currentProtected } : kw
          ),
        }
      })
      // 加白名单时同步从"已质检建议屏蔽"列表里剔除（避免一键屏蔽误带）
      if (!currentProtected && qualityCheckedSku === sku) {
        setSuggestedExcludeWords(prev => prev.filter(w => w !== keyword))
      }
    } catch (err) {
      message.error(err.message || err?.response?.data?.msg || '操作失败')
    }
  }

  // ==================== 数据加载 ====================

  const fetchSummary = useCallback(async () => {
    setSummaryLoading(true)
    try {
      const params = {}
      if (shopId) params.shop_id = shopId
      if (platform) params.platform = platform
      const res = await getAdSummary(params)
      setSummary(res.data)
    } catch {
      setSummary(null)
    } finally {
      setSummaryLoading(false)
    }
  }, [shopId, platform])

  const fetchCampaigns = useCallback(async (p = page) => {
    setListLoading(true)
    try {
      const params = { page: p, page_size: 20 }
      if (platform) params.platform = platform
      if (filterStatus) params.status = filterStatus
      if (shopId) params.shop_id = shopId
      const res = await getCampaigns(params)
      setCampaigns(res.data.items)
      setTotal(res.data.total)

      // 异步合并今日实时数据：表格先出（昨日及之前），today-summary 拉完
      // （N×2s 串行避 429）后填进 today_spend / today_orders / today_roas /
      // budget_used_pct，避免列表里这些列永远显示 0。
      // 缓存命中（5 分钟）时秒出。
      if (shopId && platform === 'wb') {
        getTodaySummaryByShop(shopId).then(tr => {
          const perCamp = tr.data?.per_campaign || {}
          setCampaigns(prev => prev.map(c => {
            const t = perCamp[c.id]
            if (!t) return c
            const todaySpend = t.spend || 0
            return {
              ...c,
              today_spend: todaySpend,
              today_orders: t.orders || 0,
              today_roas: t.roas || 0,
              today_ctr: t.ctr || 0,
              budget_used_pct: c.daily_budget && Number(c.daily_budget) > 0
                ? Math.round(todaySpend / Number(c.daily_budget) * 1000) / 10
                : c.budget_used_pct,
            }
          }))
        }).catch(() => { /* 静默：列表仍可用，只是 today_* 不更新 */ })
      }
    } catch {
      message.error('获取广告活动列表失败')
    } finally {
      setListLoading(false)
    }
  }, [page, platform, filterStatus, shopId])

  const fetchStats = useCallback(async () => {
    if (!dateRange || dateRange.length !== 2) return
    setStatsLoading(true)
    try {
      const params = {
        start_date: dateRange[0].format('YYYY-MM-DD'),
        end_date: dateRange[1].format('YYYY-MM-DD'),
      }
      if (shopId) params.shop_id = shopId
      if (platform) params.platform = platform
      const res = await getAdStats(params)
      setStatsData(res.data || [])
    } catch {
      setStatsData([])
    } finally {
      setStatsLoading(false)
    }
  }, [dateRange, shopId, platform])

  useEffect(() => {
    if (searched) {
      setPage(1)
      fetchCampaigns(1)
      fetchSummary()
      fetchStats()
    }
  }, [searched, shopId, platform])

  useEffect(() => {
    if (searched) fetchStats()
  }, [dateRange])

  // 同步由父组件管理（onSync prop）

  // ==================== 活动 创建/编辑/删除 ====================

  const handleCreateCampaign = () => {
    createForm.resetFields()
    if (platform) createForm.setFieldValue('platform', platform)
    if (shopId) createForm.setFieldValue('shop_id', shopId)
    setCreateVisible(true)
  }

  const handleCreateSubmit = async () => {
    try {
      const values = await createForm.validateFields()
      setCreateSubmitting(true)
      await createCampaign(values)
      message.success('广告活动创建成功')
      setCreateVisible(false)
      fetchCampaigns()
    } catch (err) {
      if (err.errorFields) return
      message.error(err.message || '创建失败')
    } finally {
      setCreateSubmitting(false)
    }
  }

  const handleEdit = (record) => {
    setEditingCampaign(record)
    editForm.setFieldsValue({
      name: record.name,
      daily_budget: record.daily_budget,
      total_budget: record.total_budget,
      status: record.status,
    })
    setEditVisible(true)
  }

  const handleEditSubmit = async () => {
    try {
      const values = await editForm.validateFields()
      setEditSubmitting(true)
      await updateCampaign(editingCampaign.id, values)
      message.success('广告活动更新成功')
      setEditVisible(false)
      fetchCampaigns()
      fetchSummary()
    } catch (err) {
      if (err.errorFields) return
      message.error(err.message || '更新失败')
    } finally {
      setEditSubmitting(false)
    }
  }

  const handleDelete = async (id) => {
    try {
      await deleteCampaign(id)
      message.success('广告活动已删除')
      fetchCampaigns()
      fetchSummary()
    } catch (err) {
      message.error(err.message || '删除失败')
    }
  }

  // ==================== 详情抽屉 ====================

  const handleDetail = async (id) => {
    setDetailLoading(true)
    setDetailVisible(true)
    setDetailTab('info')
    setCampaignBudget(null)
    setCampaignProducts([])
    setEditingBid(null)
    setShopListings([])
    setExpandedSkuKeys([])
    setKeywordsBySku({})
    setKeywordsLoadingSku({})
    try {
      const res = await getCampaign(id)
      setDetailData(res.data)
      fetchAdGroups(id)
      getCampaignBudget(id).then(r => setCampaignBudget(r.data)).catch(err => console.warn('预算加载失败', err))
      fetchCampaignProducts(id)
      // WB 平台拉自动屏蔽配置（轻：只查 DB，不调 WB）
      // campaignSummaryData 改为 lazy load：detailTab='info' 时才拉，避免
      // 与 getCampaignKeywords/getCampaignBudget 并发轰炸 WB 触发 429
      setAutoExcludeCfg(null)
      setCampaignSummaryData(null)
      if (res.data?.platform === 'wb') {
        getAutoExcludeConfig(id).then(r => setAutoExcludeCfg(r.data)).catch(() => setAutoExcludeCfg(null))
      }
      // 拉店铺全量 listings 以便把 sku 映射到 listing_id → ad_group_id
      if (res.data?.shop_id) {
        getListings({ shop_id: res.data.shop_id, page: 1, page_size: 200 })
          .then(r => setShopListings(r.data?.items || []))
          .catch(() => setShopListings([]))
      }
    } catch {
      message.error('获取广告详情失败')
    } finally {
      setDetailLoading(false)
    }
  }

  // sku → ad_group_id 映射（sku 即 platform_product_id）
  const getAdGroupIdBySku = (sku) => {
    if (!sku) return null
    const listing = shopListings.find(l => String(l.platform_product_id) === String(sku))
    if (!listing) return null
    const group = adGroups.find(g => g.listing_id === listing.id)
    return group ? group.id : null
  }

  const handleProductRowExpand = async (expanded, record) => {
    const sku = record.sku
    if (!expanded) {
      setExpandedSkuKeys(keys => keys.filter(k => k !== sku))
      return
    }
    setExpandedSkuKeys(keys => [...keys, sku])
    // 已缓存或正在加载则跳过
    if (keywordsBySku[sku] !== undefined || keywordsLoadingSku[sku]) return

    // WB: 调活动级关键词 API + 该 SKU 的屏蔽词
    if (platform === 'wb' && detailData?.id) {
      setKeywordsLoadingSku(m => ({ ...m, [sku]: true }))
      try {
        const r = await getCampaignKeywords(detailData.id, 7, sku)
        const kws = r.data?.keywords || []
        const excluded = r.data?.excluded_keywords || []
        setKeywordsBySku(m => ({
          ...m,
          [sku]: kws,
          [`${sku}_excluded`]: excluded,
        }))
      } catch {
        setKeywordsBySku(m => ({ ...m, [sku]: [] }))
      } finally {
        setKeywordsLoadingSku(m => ({ ...m, [sku]: false }))
      }
      return
    }

    // Ozon: 调本地 ozon_product_queries（SKU × 搜索词，含完整漏斗 + 决策派生）
    if (platform === 'ozon' && detailData?.shop_id) {
      setKeywordsLoadingSku(m => ({ ...m, [sku]: true }))
      try {
        const r = await getOzonSkuQueries(detailData.shop_id, sku, 7)
        // 把整个 data 对象塞 keywordsBySku（含 items + 顶部 summary 字段）
        setKeywordsBySku(m => ({ ...m, [sku]: r.data || { items: [] } }))
      } catch {
        setKeywordsBySku(m => ({ ...m, [sku]: { items: [] } }))
      } finally {
        setKeywordsLoadingSku(m => ({ ...m, [sku]: false }))
      }
      return
    }
    // 其他平台（保留 ad_group_id 路径作为兜底）
    const adGroupId = getAdGroupIdBySku(sku)
    if (!adGroupId) {
      setKeywordsBySku(m => ({ ...m, [sku]: [] }))
      return
    }
    setKeywordsLoadingSku(m => ({ ...m, [sku]: true }))
    try {
      const r = await getKeywords({ ad_group_id: adGroupId })
      setKeywordsBySku(m => ({ ...m, [sku]: r.data || [] }))
    } catch {
      setKeywordsBySku(m => ({ ...m, [sku]: [] }))
    } finally {
      setKeywordsLoadingSku(m => ({ ...m, [sku]: false }))
    }
  }

  const fetchCampaignProducts = async (id) => {
    setProductsLoading(true)
    try {
      const res = await getCampaignProducts(id)
      setCampaignProducts(res.data || [])
    } catch {
      setCampaignProducts([])
    } finally {
      setProductsLoading(false)
    }
  }

  const handleUpdateBid = async () => {
    if (!editingBid || newBidValue === null || !detailData) return
    setBidUpdating(true)
    try {
      // Ozon：bid 字段传 micro-rubles 字符串（历史约定）
      // WB：bid 字段传卢布字符串（后端会转戈比，同时改 search+recommendations）
      const apiBid = detailData.platform === 'ozon'
        ? String(newBidValue * 1000000)
        : String(newBidValue)
      const res = await updateCampaignBid(detailData.id, { sku: editingBid.sku, bid: apiBid })

      // WB 可能部分成功：updated 里的广告位改了，skipped 里的没启用被跳过
      if (detailData.platform === 'wb') {
        const { updated = [], skipped = [] } = res?.data || {}
        const placementLabel = {
          combined: '搜索+推荐',
          search: '搜索',
          recommendations: '推荐',
        }
        if (skipped.length > 0) {
          Modal.warning({
            title: '出价部分修改成功',
            content: (
              <div>
                <p>
                  已更新：
                  {updated.map(p => placementLabel[p] || p).join('、') || '无'}
                </p>
                <p style={{ color: '#faad14' }}>
                  未启用跳过：
                  {skipped.map(p => placementLabel[p] || p).join('、')}
                </p>
                <p style={{ marginTop: 12, fontSize: 12, color: '#999' }}>
                  被跳过的广告位需要先到 WB 后台启用才能修改出价。WB 修改一般 3 分钟内生效。
                </p>
              </div>
            ),
            okText: '我知道了',
          })
        } else {
          message.success(`出价修改成功：${updated.map(p => placementLabel[p] || p).join('、')}`)
        }
      } else {
        message.success('出价修改成功')
      }

      setEditingBid(null)
      setNewBidValue(null)
      fetchCampaignProducts(detailData.id)
    } catch (err) {
      message.error(err.message || '出价修改失败')
    } finally {
      setBidUpdating(false)
    }
  }

  // ==================== 广告组 CRUD ====================

  const fetchAdGroups = async (campaignId) => {
    setGroupsLoading(true)
    try {
      const res = await getAdGroups({ campaign_id: campaignId })
      setAdGroups(res.data || [])
    } catch {
      setAdGroups([])
    } finally {
      setGroupsLoading(false)
    }
  }

  const handleCreateGroup = () => {
    setEditingGroup(null)
    groupForm.resetFields()
    groupForm.setFieldValue('campaign_id', detailData?.id)
    setGroupFormVisible(true)
  }

  const handleEditGroup = (record) => {
    setEditingGroup(record)
    groupForm.setFieldsValue(record)
    setGroupFormVisible(true)
  }

  const handleGroupSubmit = async () => {
    try {
      const values = await groupForm.validateFields()
      setGroupSubmitting(true)
      if (editingGroup) {
        await updateAdGroup(editingGroup.id, values)
        message.success('广告组更新成功')
      } else {
        values.campaign_id = detailData.id
        await createAdGroup(values)
        message.success('广告组创建成功')
      }
      setGroupFormVisible(false)
      fetchAdGroups(detailData.id)
    } catch (err) {
      if (err.errorFields) return
      message.error(err.message || '操作失败')
    } finally {
      setGroupSubmitting(false)
    }
  }

  const handleDeleteGroup = async (id) => {
    try {
      await deleteAdGroup(id)
      message.success('广告组已删除')
      fetchAdGroups(detailData.id)
      setSelectedGroupId(null)
      setKeywords([])
    } catch (err) {
      message.error(err.message || '删除失败')
    }
  }

  // ==================== 关键词 CRUD ====================

  const fetchKeywords = async (groupId) => {
    setKeywordsLoading(true)
    setSelectedGroupId(groupId)
    try {
      const res = await getKeywords({ ad_group_id: groupId })
      setKeywords(res.data || [])
    } catch {
      setKeywords([])
    } finally {
      setKeywordsLoading(false)
    }
  }

  const handleCreateKeyword = () => {
    setEditingKeyword(null)
    kwForm.resetFields()
    kwForm.setFieldValue('ad_group_id', selectedGroupId)
    setKwFormVisible(true)
  }

  const handleEditKeyword = (record) => {
    setEditingKeyword(record)
    kwForm.setFieldsValue(record)
    setKwFormVisible(true)
  }

  const handleKwSubmit = async () => {
    try {
      const values = await kwForm.validateFields()
      setKwSubmitting(true)
      if (editingKeyword) {
        await updateKeyword(editingKeyword.id, values)
        message.success('关键词更新成功')
      } else {
        values.ad_group_id = selectedGroupId
        await createKeyword(values)
        message.success('关键词创建成功')
      }
      setKwFormVisible(false)
      fetchKeywords(selectedGroupId)
    } catch (err) {
      if (err.errorFields) return
      message.error(err.message || '操作失败')
    } finally {
      setKwSubmitting(false)
    }
  }

  const handleBatchKeywords = () => {
    kwBatchForm.resetFields()
    setKwBatchVisible(true)
  }

  const handleBatchKwSubmit = async () => {
    try {
      const values = await kwBatchForm.validateFields()
      setKwSubmitting(true)
      const kwTexts = values.keywords_text.split('\n').map(s => s.trim()).filter(Boolean)
      if (kwTexts.length === 0) {
        message.warning('请输入至少一个关键词')
        return
      }
      await batchCreateKeywords({
        ad_group_id: selectedGroupId,
        keywords: kwTexts,
        match_type: values.match_type || 'broad',
        bid: values.bid,
        is_negative: values.is_negative || 0,
      })
      message.success(`成功添加 ${kwTexts.length} 个关键词`)
      setKwBatchVisible(false)
      fetchKeywords(selectedGroupId)
    } catch (err) {
      if (err.errorFields) return
      message.error(err.message || '批量添加失败')
    } finally {
      setKwSubmitting(false)
    }
  }

  const handleDeleteKeyword = async (id) => {
    try {
      await deleteKeyword(id)
      message.success('关键词已删除')
      fetchKeywords(selectedGroupId)
    } catch (err) {
      message.error(err.message || '删除失败')
    }
  }

  // ==================== 数据导出 ====================

  const handleExport = async () => {
    if (!dateRange || dateRange.length !== 2) {
      message.warning('请选择导出日期范围')
      return
    }
    setExporting(true)
    try {
      const params = {
        start_date: dateRange[0].format('YYYY-MM-DD'),
        end_date: dateRange[1].format('YYYY-MM-DD'),
      }
      if (shopId) params.shop_id = shopId
      if (platform) params.platform = platform
      const res = await exportAdStats(params)
      const url = window.URL.createObjectURL(new Blob([res]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `ad_stats_${params.start_date}_${params.end_date}.csv`)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
      message.success('导出成功')
    } catch (err) {
      message.error(err.message || '导出失败')
    } finally {
      setExporting(false)
    }
  }

  // ==================== ROI告警 ====================

  const handleShowAlerts = async () => {
    setAlertsVisible(true)
    fetchAlerts(1)
  }

  const fetchAlerts = async (p = 1) => {
    setAlertsLoading(true)
    setAlertsPage(p)
    try {
      const res = await getAlerts({ page: p, page_size: 10 })
      setAlerts(res.data.items || [])
      setAlertsTotal(res.data.total || 0)
    } catch {
      setAlerts([])
    } finally {
      setAlertsLoading(false)
    }
  }

  // ==================== 告警配置 ====================

  const handleShowConfig = async () => {
    setConfigVisible(true)
    try {
      const res = await getAlertConfig()
      setAlertConfig(res.data)
      configForm.setFieldsValue(res.data)
    } catch {
      message.error('获取告警配置失败')
    }
  }

  const handleConfigSubmit = async () => {
    try {
      const values = await configForm.validateFields()
      setConfigSubmitting(true)
      await updateAlertConfig(values)
      message.success('告警配置已更新')
      setConfigVisible(false)
    } catch (err) {
      if (err.errorFields) return
      message.error(err.message || '更新失败')
    } finally {
      setConfigSubmitting(false)
    }
  }

  // ==================== 可配置列系统 ====================

  const ALL_COLUMNS = {
    campaign_name: {
      title: '活动名称', dataIndex: 'name', fixed: true, width: 220,
      render: (name, record) => (
        <div>
          <a onClick={() => handleDetail(record.id)} style={{ fontWeight: 500 }}>{name || '-'}</a>
          <div style={{ fontSize: 12, color: '#999', marginTop: 2 }}>ID: {record.platform_campaign_id || record.id}</div>
        </div>
      ),
    },
    status: {
      title: '状态', dataIndex: 'status', fixed: true, width: 90,
      render: s => {
        const cfg = { active: { color: '#52c41a', text: '投放中' }, paused: { color: '#faad14', text: '已暂停' }, stopped: { color: '#ff4d4f', text: '已停止' }, archived: { color: '#d9d9d9', text: '已归档' } }[s] || { color: '#d9d9d9', text: s }
        return <Space size={4}><span style={{ width: 6, height: 6, borderRadius: '50%', background: cfg.color, display: 'inline-block' }} /><span style={{ fontSize: 13 }}>{cfg.text}</span></Space>
      },
    },
    today_spend: { title: '今日花费', dataIndex: 'today_spend', group: '今日数据', width: 100, align: 'right', render: v => v ? `₽${v.toLocaleString()}` : '-' },
    today_roas: {
      title: '今日ROAS', dataIndex: 'today_roas', group: '今日数据', width: 100, align: 'right',
      render: (v, r) => { if (!v) return '-'; const t = r.target_roas || 3.0; const c = v >= t ? '#52c41a' : v >= t * 0.7 ? '#faad14' : '#ff4d4f'; return <span style={{ color: c, fontWeight: 500 }}>{v}x</span> },
    },
    today_orders: { title: '今日订单', dataIndex: 'today_orders', group: '今日数据', width: 90, align: 'right', render: v => v || '-' },
    today_ctr: { title: '今日CTR', dataIndex: 'today_ctr', group: '今日数据', width: 90, align: 'right', render: v => v ? `${v}%` : '-' },
    spend_7d: { title: '7天花费', dataIndex: 'spend_7d', group: '7天数据', width: 100, align: 'right', render: v => v ? `₽${v.toLocaleString()}` : '-' },
    avg_roas_7d: {
      title: '7天均ROAS', dataIndex: 'avg_roas_7d', group: '7天数据', width: 110, align: 'right',
      render: (v, r) => { if (!v) return '-'; const t = r.target_roas || 3.0; const c = v >= t ? '#52c41a' : v >= t * 0.7 ? '#faad14' : '#ff4d4f'; return <span style={{ color: c, fontWeight: 500 }}>{v}x</span> },
    },
    roas_trend: {
      title: 'ROAS趋势', dataIndex: 'roas_trend', group: '7天数据', width: 120,
      render: trend => {
        if (!trend || trend.length === 0) return '-'
        const max = Math.max(...trend)
        return (
          <div style={{ display: 'flex', gap: 2, alignItems: 'flex-end', height: 24 }}>
            {trend.slice(-7).map((v, i) => {
              const h = max > 0 ? Math.max((v / max) * 20, 2) : 2
              const c = v >= 3 ? '#52c41a' : v >= 1.8 ? '#faad14' : '#ff4d4f'
              return <Tooltip key={i} title={`${v}x`}><div style={{ width: 10, height: h, background: c, borderRadius: 2, cursor: 'help' }} /></Tooltip>
            })}
          </div>
        )
      },
    },
    orders_7d: { title: '7天订单', dataIndex: 'orders_7d', group: '7天数据', width: 90, align: 'right', render: v => v || '-' },
    daily_budget: { title: '日预算', dataIndex: 'daily_budget', group: '预算', width: 90, align: 'right', render: v => v ? `₽${v}` : '不限' },
    budget_used_pct: {
      title: '预算进度', dataIndex: 'budget_used_pct', group: '预算', width: 130,
      render: pct => { if (!pct) return '-'; const c = pct >= 100 ? '#ff4d4f' : pct >= 80 ? '#faad14' : '#52c41a'; return <Progress percent={Math.min(pct, 100)} size="small" strokeColor={c} format={() => `${pct}%`} /> },
    },
    budget_days_left: { title: '剩余天数', dataIndex: 'budget_days_left', group: '预算', width: 90, render: v => v != null ? `${v}天` : '-' },
    ozon_bid_type: { title: '出价类型', dataIndex: 'ozon_bid_type', group: 'Ozon', platforms: ['ozon'], width: 100, render: v => v || '-' },
    wb_campaign_type: { title: '活动类型', dataIndex: 'wb_campaign_type', group: 'WB', platforms: ['wb'], width: 100, render: v => v || '-' },
    payment_type: {
      title: '付费类型', dataIndex: 'payment_type', group: '基础', width: 90,
      render: v => {
        const map = { cpm: { label: 'CPM', color: 'blue', tip: '按1000次曝光付费' },
                      cpc: { label: 'CPC', color: 'green', tip: '按点击付费' },
                      cpo: { label: 'CPO', color: 'orange', tip: '按订单付费' } }
        const cfg = map[v] || { label: v || '-', color: 'default', tip: '' }
        return <Tooltip title={cfg.tip}><Tag color={cfg.color} style={{ margin: 0 }}>{cfg.label}</Tag></Tooltip>
      }
    },
  }

  const PLATFORM_DEFAULT_COLS = {
    ozon: ['campaign_name', 'payment_type', 'status', 'today_spend', 'today_roas', 'today_orders', 'avg_roas_7d', 'roas_trend', 'budget_used_pct', 'daily_budget'],
    wb: ['campaign_name', 'payment_type', 'status', 'today_spend', 'today_roas', 'today_orders', 'avg_roas_7d', 'spend_7d', 'budget_used_pct'],
    yandex: ['campaign_name', 'status', 'today_spend', 'today_roas', 'today_orders', 'avg_roas_7d'],
  }

  const storageKey = `ads_columns_${platform}`
  const [visibleColumns, setVisibleColumns] = useState(() => {
    try { const s = localStorage.getItem(storageKey); return s ? JSON.parse(s) : PLATFORM_DEFAULT_COLS[platform] || PLATFORM_DEFAULT_COLS.ozon } catch { return PLATFORM_DEFAULT_COLS[platform] || PLATFORM_DEFAULT_COLS.ozon }
  })

  useEffect(() => {
    setVisibleColumns(PLATFORM_DEFAULT_COLS[platform] || PLATFORM_DEFAULT_COLS.ozon)
  }, [platform])

  const handleColumnChange = (cols) => {
    setVisibleColumns(cols)
    localStorage.setItem(storageKey, JSON.stringify(cols))
  }

  // 构建表格列
  const tableColumns = [
    ...['campaign_name', 'status'].map(k => ({ key: k, ...ALL_COLUMNS[k] })),
    ...visibleColumns
      .filter(k => !['campaign_name', 'status'].includes(k) && ALL_COLUMNS[k])
      .filter(k => { const col = ALL_COLUMNS[k]; return !col.platforms || col.platforms.includes(platform) })
      .map(k => ({ key: k, ...ALL_COLUMNS[k] })),
    {
      title: <ColumnSelector platform={platform} allColumns={ALL_COLUMNS} visibleColumns={visibleColumns} defaultColumns={PLATFORM_DEFAULT_COLS} onChange={handleColumnChange} />,
      key: 'actions', fixed: 'right', width: 50,
      render: () => null,
    },
  ]

  // ==================== 图表配置 ====================

  const getChartOption = () => {
    const dateMap = {}
    statsData.forEach(item => {
      if (!dateMap[item.stat_date]) {
        dateMap[item.stat_date] = { spend: 0, clicks: 0, impressions: 0, revenue: 0 }
      }
      dateMap[item.stat_date].spend += item.spend
      dateMap[item.stat_date].clicks += item.clicks
      dateMap[item.stat_date].impressions += item.impressions
      dateMap[item.stat_date].revenue += item.revenue
    })
    const dates = Object.keys(dateMap).sort()
    const spendArr = dates.map(d => dateMap[d].spend)
    const clicksArr = dates.map(d => dateMap[d].clicks)
    const revenueArr = dates.map(d => dateMap[d].revenue)

    return {
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
      legend: { data: ['花费 (₽)', '收入 (₽)', '点击'] },
      grid: { left: 60, right: 60, top: 40, bottom: 30 },
      xAxis: { type: 'category', data: dates },
      yAxis: [
        { type: 'value', name: '金额 (₽)', position: 'left' },
        { type: 'value', name: '点击', position: 'right' },
      ],
      series: [
        { name: '花费 (₽)', type: 'bar', data: spendArr, itemStyle: { color: '#ff7875' }, barMaxWidth: 30 },
        { name: '收入 (₽)', type: 'bar', data: revenueArr, itemStyle: { color: '#95de64' }, barMaxWidth: 30 },
        { name: '点击', type: 'line', yAxisIndex: 1, data: clicksArr, smooth: true, itemStyle: { color: '#597ef7' } },
      ],
    }
  }

  // 广告组表格列
  const groupColumns = [
    { title: '名称', dataIndex: 'name', key: 'name', ellipsis: true },
    { title: '出价 (₽)', dataIndex: 'bid', key: 'bid', width: 100, render: v => v != null ? `₽${v}` : '-' },
    { title: '关键词数', dataIndex: 'keyword_count', key: 'keyword_count', width: 80 },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: s => <Badge color={AD_STATUS[s]?.color || 'default'} text={AD_STATUS[s]?.label || s} />,
    },
    {
      title: '操作', key: 'action', width: 200,
      render: (_, record) => (
        <Space size="small">
          <Button type="link" size="small" onClick={() => fetchKeywords(record.id)}>关键词</Button>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEditGroup(record)} />
          <Popconfirm title="确定删除此广告组？" onConfirm={() => handleDeleteGroup(record.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  // 关键词表格列
  const keywordColumns = [
    { title: '关键词', dataIndex: 'keyword', key: 'keyword', ellipsis: true },
    { title: '匹配类型', dataIndex: 'match_type', key: 'match_type', width: 100, render: v => MATCH_TYPES[v] || v },
    { title: '出价 (₽)', dataIndex: 'bid', key: 'bid', width: 90, render: v => v != null ? `₽${v}` : '-' },
    {
      title: '类型', dataIndex: 'is_negative', key: 'is_negative', width: 80,
      render: v => v ? <Tag color="red">否定</Tag> : <Tag color="blue">正向</Tag>,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: s => <Badge color={AD_STATUS[s]?.color || (s === 'deleted' ? 'red' : 'default')} text={s === 'deleted' ? '已删除' : (AD_STATUS[s]?.label || s)} />,
    },
    {
      title: '操作', key: 'action', width: 120,
      render: (_, record) => (
        <Space size="small">
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEditKeyword(record)} />
          <Popconfirm title="确定删除此关键词？" onConfirm={() => handleDeleteKeyword(record.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  // ==================== 渲染 ====================

  // 商品单元格：图 + 标题 + SKU 徽章（Ozon 有 image/title；WB 用 WbProductImg 探测 basket）
  const renderProductCell = (record) => {
    const sku = record.sku
    const title = record.title || record.subject_name || `nm_id ${sku}`
    const img = record.image
    const isWb = detailData?.platform === 'wb'
    return (
      <Space align="center" size="middle">
        {isWb ? (
          <WbProductImg nmId={sku} size={56} />
        ) : img ? (
          <img src={img} alt="" style={{ width: 56, height: 56, objectFit: 'cover', borderRadius: 6, border: '1px solid #f0f0f0' }} />
        ) : (
          <div style={{
            width: 56, height: 56, background: '#fafafa', borderRadius: 6, border: '1px solid #f0f0f0',
            display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#ccc', fontSize: 11,
          }}>无图</div>
        )}
        <div style={{ minWidth: 0, maxWidth: 400 }}>
          <Tooltip title={title} placement="topLeft">
            <div style={{
              fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>{title}</div>
          </Tooltip>
          <Space size={4} style={{ marginTop: 4 }}>
            <Tag style={{ marginRight: 0, fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>
              {detailData?.platform === 'wb' ? `nm_id ${sku}` : `SKU ${sku}`}
            </Tag>
            {record.product_code && (
              <Tag color="blue" style={{ fontSize: 11, fontFamily: 'ui-monospace, monospace' }}>
                编码 {record.product_code}
              </Tag>
            )}
          </Space>
        </div>
      </Space>
    )
  }

  // 展开行：展示关键词子表 / 空态 / loading
  const renderKeywordsExpandedRow = (record) => {
    const sku = record.sku
    const loading = !!keywordsLoadingSku[sku]
    const kws = keywordsBySku[sku]

    if (loading) {
      return <div style={{ padding: 16, textAlign: 'center', color: '#999' }}>加载关键词中...</div>
    }

    // WB：活动级关键词（所有 SKU 共享）
    if (platform === 'wb') {
      const excluded = keywordsBySku[`${sku}_excluded`] || []
      if (!kws || kws.length === 0) {
        return (
          <div style={{ padding: 12, background: '#fafafa', borderRadius: 4 }}>
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={<span style={{ fontSize: 13 }}>近7天无关键词数据（活动可能还没曝光）</span>}
            />
            {excluded.length > 0 && (
              <div style={{ marginTop: 12, padding: 10, background: '#fff', borderRadius: 4 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>🚫 已屏蔽 {excluded.length} 个关键词：</Text>
                <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                  {excluded.map(w => <Tag key={w} color="red" style={{ fontSize: 11 }}>{w}</Tag>)}
                </div>
              </div>
            )}
          </div>
        )
      }
      return (
        <div style={{ padding: 8, background: '#fafbff', borderRadius: 4, border: '1px solid #e6edff' }}>
          {/* 顶部信息 + 操作按钮栏 */}
          <div style={{ marginBottom: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Space size={4}>
                <Text type="secondary" style={{ fontSize: 12 }}>活动级关键词（所有 SKU 共享）·</Text>
                <Text strong style={{ fontSize: 13 }}>{kws.length} 个</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>· 近7天实际触发</Text>
                {excluded.length > 0 && (
                  <Tag color="default" style={{ marginLeft: 8, fontSize: 11 }}>已屏蔽 {excluded.length} 个</Tag>
                )}
              </Space>
              <Space size={8}>
                <Button size="small" icon={<SettingOutlined />}
                  onClick={() => setRulesDrawerOpen(true)}>
                  屏蔽规则
                </Button>
                <Button size="small" type="primary"
                  icon={<SearchOutlined />}
                  onClick={() => {
                    const suggested = getSuggestedExcludes(kws)
                    setQualityCheckedSku(sku)
                    setSuggestedExcludeWords(suggested.map(s => s.keyword))
                    if (suggested.length === 0) message.success('质检通过，无建议屏蔽词')
                    else message.info(`发现 ${suggested.length} 个不合格关键词，已标红`)
                  }}>
                  关键词质检
                </Button>
                {qualityCheckedSku === sku && suggestedExcludeWords.length > 0 && (
                  <Button size="small" type="primary" danger loading={excludingKws}
                    icon={<DeleteOutlined />}
                    onClick={() => {
                      Modal.confirm({
                        title: `确认屏蔽 ${suggestedExcludeWords.length} 个不合格关键词？`,
                        icon: <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />,
                        width: 500,
                        content: (
                          <div>
                            <div style={{ maxHeight: 200, overflow: 'auto', marginTop: 8 }}>
                              {suggestedExcludeWords.map(w => (
                                <Tag key={w} color="volcano" style={{ margin: 2, fontSize: 11 }}>{w}</Tag>
                              ))}
                            </div>
                            <div style={{ marginTop: 10, padding: 8, background: '#fff2f0', borderRadius: 4, fontSize: 12, color: '#cf1322' }}>
                              屏蔽后这些词将不再触发此商品的广告展示。
                            </div>
                          </div>
                        ),
                        okText: '确认屏蔽',
                        okType: 'danger',
                        onOk: async () => {
                          // 兜底：发请求前再过滤一次含空格短语，防止 stale state
                          const sendable = suggestedExcludeWords.filter(w => !w.includes(' '))
                          const phraseDropped = suggestedExcludeWords.filter(w => w.includes(' '))
                          if (sendable.length === 0) {
                            message.info(`${phraseDropped.length} 个候选词都是含空格短语，WB 不支持屏蔽，请到 WB 后台手动添加`, 5)
                            return
                          }
                          setExcludingKws(true)
                          try {
                            const res = await excludeKeywords(detailData.id, parseInt(sku), sendable)
                            const added = res.data?.added || []
                            const skipped = res.data?.skipped_protected || []
                            const dropped = res.data?.dropped_invalid || []
                            const wbRejected = dropped.filter(d => !d.includes(' '))
                            const allPhraseDropped = [...phraseDropped, ...dropped.filter(d => d.includes(' '))]

                            // 简洁顶部提示
                            const headParts = []
                            if (added.length > 0) headParts.push(`屏蔽 ${added.length} 个`)
                            if (skipped.length > 0) headParts.push(`白名单跳过 ${skipped.length} 个`)
                            if (allPhraseDropped.length > 0) headParts.push(`${allPhraseDropped.length} 个含空格短语未送 WB`)
                            if (wbRejected.length > 0) headParts.push(`WB 拒绝 ${wbRejected.length} 个`)
                            const headMsg = headParts.length ? headParts.join('；') : '未屏蔽任何词'
                            if (added.length > 0) message.success(headMsg, 4)
                            else message.info(headMsg, 4)

                            // 有 WB 拒绝词或含空格短语 → 弹 notification 列出具体词 + 解释
                            if (wbRejected.length > 0 || allPhraseDropped.length > 0) {
                              notification.warning({
                                message: '部分关键词未屏蔽',
                                duration: 0,  // 用户手动关
                                description: (
                                  <div style={{ fontSize: 12 }}>
                                    {wbRejected.length > 0 && (
                                      <div style={{ marginBottom: 8 }}>
                                        <div style={{ marginBottom: 4 }}>
                                          <strong>WB 拒绝（{wbRejected.length} 个）：</strong>
                                          <Tooltip title="WB 接口报 'norm_query is not valid for nm'。常见原因：①该词是商品类目核心词（如卖饰品时屏蔽 «украшения»），WB 不允许屏蔽自己的核心词；②该词形不在 WB 对该商品的可识别 norm_query 集合里。可到 WB 后台手动尝试。">
                                            <span style={{ color: '#1677ff', cursor: 'help', marginLeft: 4 }}>为什么？</span>
                                          </Tooltip>
                                        </div>
                                        <div>{wbRejected.map(w => (
                                          <Tag key={w} color="volcano" style={{ margin: 2, fontSize: 11 }}>{w}</Tag>
                                        ))}</div>
                                      </div>
                                    )}
                                    {allPhraseDropped.length > 0 && (
                                      <div>
                                        <div style={{ marginBottom: 4 }}>
                                          <strong>含空格短语未送 WB（{allPhraseDropped.length} 个）：</strong>
                                          <Tooltip title="当前前端兜底跳过含空格短语。WB 文档实际支持空格短语，但需要是该商品的归一化 norm_query。后续会改成「按 WB 实际反馈处理」。">
                                            <span style={{ color: '#1677ff', cursor: 'help', marginLeft: 4 }}>说明</span>
                                          </Tooltip>
                                        </div>
                                        <div>{allPhraseDropped.map(w => (
                                          <Tag key={w} color="default" style={{ margin: 2, fontSize: 11 }}>{w}</Tag>
                                        ))}</div>
                                      </div>
                                    )}
                                  </div>
                                ),
                              })
                            }
                            setSuggestedExcludeWords([])
                            setQualityCheckedSku(null)
                            // 直接 refetch 替代"折叠 + 0.5s 后展开"——后者依赖
                            // handleProductRowExpand 里读 keywordsBySku 判 undefined，
                            // 但闭包捕获的是旧 state 快照（已被设为 undefined），
                            // 走不进 fetch 分支 → 关键词列表消失
                            if (platform === 'wb' && detailData?.id) {
                              try {
                                const r = await getCampaignKeywords(detailData.id, 7, sku)
                                const kws = r.data?.keywords || []
                                const excluded = r.data?.excluded_keywords || []
                                setKeywordsBySku(m => ({
                                  ...m, [sku]: kws, [`${sku}_excluded`]: excluded,
                                }))
                              } catch { /* refetch 失败不致命，UI 仍可见原数据 */ }
                            }
                          } catch (err) {
                            message.error(err.message || err?.response?.data?.msg || '屏蔽失败')
                          } finally {
                            setExcludingKws(false)
                          }
                        },
                      })
                    }}>
                    一键屏蔽 {suggestedExcludeWords.length} 个
                  </Button>
                )}
              </Space>
            </div>
          </div>
          {qualityCheckedSku === sku && suggestedExcludeWords.length > 0 && (
            <div style={{ marginBottom: 8, padding: '8px 12px', background: '#fff',
                          border: '1px solid #ffccc7', borderRadius: 4 }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                <Text strong style={{ fontSize: 12, color: '#cf1322', whiteSpace: 'nowrap' }}>
                  质检发现 {suggestedExcludeWords.length} 个建议屏蔽词：
                </Text>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, flex: 1 }}>
                  {suggestedExcludeWords.map(w => {
                    const row = kws.find(k => k.keyword === w)
                    const tip = row
                      ? `点击定位 · 曝光${(row.views||0).toLocaleString()} · 点击${row.clicks||0} · CTR ${row.ctr||0}% · 花费¥${(row.sum||0).toFixed(2)}`
                      : '点击定位'
                    return (
                      <Tooltip key={w} title={tip}>
                        <Tag color="volcano" style={{ margin: 0, fontSize: 11, cursor: 'pointer' }}
                          onClick={() => {
                            const idx = kws.findIndex(k => k.keyword === w)
                            if (idx >= 0) {
                              setKwTablePageMap(m => ({ ...m, [sku]: Math.floor(idx / 20) + 1 }))
                            }
                          }}>
                          {w}
                        </Tag>
                      </Tooltip>
                    )
                  })}
                </div>
              </div>
            </div>
          )}
          <Table
            size="small"
            rowKey="keyword"
            dataSource={kws}
            pagination={{
              pageSize: 20, size: 'small', showSizeChanger: false,
              current: kwTablePageMap[sku] || 1,
              onChange: (p) => setKwTablePageMap(m => ({ ...m, [sku]: p })),
            }}
            rowClassName={(r) =>
              qualityCheckedSku === sku && suggestedExcludeWords.includes(r.keyword)
                ? 'row-suggested-exclude' : ''
            }
            columns={[
              { title: '关键词', dataIndex: 'keyword', key: 'keyword', ellipsis: true,
                render: (v, r) => {
                  const statusMap = {
                    active:     { label: '活跃', color: 'green' },
                    stable:     { label: '稳定', color: 'blue' },
                    low_effect: { label: '低效', color: 'orange' },
                    occasional: { label: '偶发', color: 'default' },
                  }
                  const s = statusMap[r.status] || {}
                  const isSuggested = qualityCheckedSku === sku && suggestedExcludeWords.includes(v)
                  const isPhrase = isPhraseUnsupported(r)
                  return (
                    <Space size={4}>
                      {r.is_excluded && <Tag color="red" style={{ margin: 0, fontSize: 11 }}>已屏蔽</Tag>}
                      {isPhrase && !r.is_excluded && (
                        <Tooltip title="WB 接口仅支持单词屏蔽，含空格短语无法通过 API 屏蔽。如确需屏蔽，请到 WB 后台手动添加">
                          <Tag color="default" style={{ margin: 0, fontSize: 11, cursor: 'help' }}>短语</Tag>
                        </Tooltip>
                      )}
                      {isSuggested && !r.is_excluded && <Tag color="volcano" style={{ margin: 0, fontSize: 11 }}>建议屏蔽</Tag>}
                      {!r.is_excluded && !isSuggested && !isPhrase && s.label && <Tag color={s.color} style={{ margin: 0, fontSize: 11 }}>{s.label}</Tag>}
                      <Tooltip title={`${v}（${r.active_days || 0}/${r.total_days || 7}天出现${r.first_seen ? `，首次 ${r.first_seen}` : ''}${r.last_seen && r.last_seen !== r.first_seen ? `，末次 ${r.last_seen}` : ''}）`} placement="topLeft">
                        <span style={
                          r.is_excluded ? { textDecoration: 'line-through', color: '#999' }
                          : isSuggested ? { color: '#cf1322', fontWeight: 500 }
                          : {}
                        }>{v}</span>
                      </Tooltip>
                    </Space>
                  )
                }},
              { title: '首次出现', dataIndex: 'first_seen', key: 'first_seen', width: 100,
                sorter: (a, b) => (a.first_seen || '').localeCompare(b.first_seen || ''),
                render: v => v ? v.slice(5) : '-' },
              { title: '天数', dataIndex: 'active_days', key: 'active_days', width: 60, align: 'center',
                sorter: (a, b) => (a.active_days||0) - (b.active_days||0),
                render: (v, r) => `${v||0}/${r.total_days||7}` },
              { title: '曝光', dataIndex: 'views', key: 'views', width: 80, align: 'right',
                sorter: (a, b) => (a.views||0) - (b.views||0),
                render: v => (v || 0).toLocaleString() },
              { title: '点击', dataIndex: 'clicks', key: 'clicks', width: 70, align: 'right',
                sorter: (a, b) => (a.clicks||0) - (b.clicks||0),
                render: v => (v || 0).toLocaleString() },
              { title: 'CTR', dataIndex: 'ctr', key: 'ctr', width: 80, align: 'right',
                sorter: (a, b) => (a.ctr||0) - (b.ctr||0),
                render: v => v > 0 ? `${v}%` : '-' },
              { title: 'CPC', key: 'cpc', width: 90, align: 'right',
                sorter: (a, b) => {
                  const ac = a.clicks > 0 ? a.sum/a.clicks : 0
                  const bc = b.clicks > 0 ? b.sum/b.clicks : 0
                  return ac - bc
                },
                render: (_, r) => r.clicks > 0 ? `₽${(r.sum/r.clicks).toFixed(2)}` : '-' },
              { title: 'CPM', key: 'cpm', width: 90, align: 'right',
                sorter: (a, b) => {
                  const am = a.views > 0 ? a.sum/a.views*1000 : 0
                  const bm = b.views > 0 ? b.sum/b.views*1000 : 0
                  return am - bm
                },
                render: (_, r) => r.views > 0 ? `₽${(r.sum/r.views*1000).toFixed(2)}` : '-' },
              { title: '花费', dataIndex: 'sum', key: 'sum', width: 100, align: 'right',
                sorter: (a, b) => (a.sum||0) - (b.sum||0),
                defaultSortOrder: 'descend',
                render: v => v > 0 ? `₽${v.toFixed(2)}` : '-' },
              { title: <Tooltip title="按点击占比估算（非精确归因）">估算订单</Tooltip>,
                dataIndex: 'est_orders', key: 'est_orders', width: 90, align: 'right',
                sorter: (a, b) => (a.est_orders||0) - (b.est_orders||0),
                render: v => v > 0 ? v.toFixed(1) : '-' },
              { title: <Tooltip title="按点击占比估算（非精确归因）">估算加购</Tooltip>,
                dataIndex: 'est_atbs', key: 'est_atbs', width: 90, align: 'right',
                sorter: (a, b) => (a.est_atbs||0) - (b.est_atbs||0),
                render: v => v > 0 ? v.toFixed(1) : '-' },
              { title: <Tooltip title="估算营收 / 花费（按点击占比归因）">估算ROAS</Tooltip>,
                dataIndex: 'est_roas', key: 'est_roas', width: 100, align: 'right',
                sorter: (a, b) => (a.est_roas||0) - (b.est_roas||0),
                render: v => {
                  if (!v || v <= 0) return '-'
                  const color = v >= 5 ? '#52c41a' : v >= 3 ? '#faad14' : '#ff4d4f'
                  return <span style={{ color, fontWeight: 500 }}>{v.toFixed(1)}x</span>
                }},
              { title: <Tooltip title="勾选后此词不会进入「建议屏蔽」，「一键屏蔽」也会跳过。可随时取消。">🛡 不屏蔽</Tooltip>,
                key: 'is_protected', width: 90, align: 'center',
                render: (_, r) => (
                  <Checkbox
                    checked={!!r.is_protected}
                    disabled={r.is_excluded}
                    onChange={() => toggleProtected(sku, r.keyword, !!r.is_protected)}
                  />
                ) },
            ]}
          />
          {excluded.length > 0 && (
            <div style={{ marginTop: 12, padding: 10, background: '#fff1f0', borderRadius: 4 }}>
              <Text type="secondary" style={{ fontSize: 12, fontWeight: 500 }}>
                🚫 已屏蔽关键词（{excluded.length} 个）— 以下词不会触发此商品广告展示
              </Text>
              <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {excluded.map(w => (
                  <Tag key={w} style={{ fontSize: 11, color: '#cf1322', background: '#fff1f0', border: '1px solid #ffa39e' }}>
                    {w}
                  </Tag>
                ))}
              </div>
            </div>
          )}
        </div>
      )
    }

    // Ozon: 走 ozon_product_queries（SKU × 搜索词，含完整漏斗）
    if (platform === 'ozon') {
      const data = kws || {}
      const items = data.items || []
      if (items.length === 0) {
        return (
          <div style={{ padding: 12, background: '#fafafa', borderRadius: 4 }}>
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={<span style={{ fontSize: 13 }}>暂无该 SKU 的搜索词数据。可点击右上「立即同步」从 Ozon 拉取最新（需 Premium 订阅）</span>}
            >
              <Button size="small" type="primary" onClick={async () => {
                try {
                  await syncOzonSkuQueries(detailData.shop_id, 7)
                  message.success('同步任务已提交，1-3 分钟后请重新展开此 SKU')
                } catch (err) {
                  message.error(err.message || '同步失败')
                }
              }}>立即同步</Button>
            </Empty>
          </div>
        )
      }
      // 决策标签算法（前端先实现简版，将来挪后端可配阈值）
      const labelOf = (r) => {
        if (r.orders >= 3 && r.cvr >= 2) return { tag: '🔥 明星', color: 'red' }
        if (r.impressions >= 100 && r.orders === 0) return { tag: '🗑️ 低效', color: 'default' }
        if (r.cvr >= 1.5 && r.orders < 3) return { tag: '📈 成长', color: 'green' }
        if (r.impressions >= 200 && r.cvr < 0.5) return { tag: '💡 机会', color: 'blue' }
        return { tag: '普通', color: 'default' }
      }
      return (
        <div style={{ padding: 8, background: '#fafafa', borderRadius: 4 }}>
          <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Space size={6}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                Ozon SKU × 搜索词
                {data.date_from && data.date_to && ` · ${data.date_from} ~ ${data.date_to}`}
              </Text>
              <Text strong style={{ fontSize: 13 }}>{items.length} 个词</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                · 共 {data.total_clicks} 点击 · {data.total_orders} 单 · ¥{data.total_revenue?.toLocaleString()}
              </Text>
            </Space>
            <Button size="small" onClick={async () => {
              try {
                await syncOzonSkuQueries(detailData.shop_id, 7)
                message.success('同步任务已提交，1-3 分钟后请重新展开')
              } catch (err) {
                message.error(err.message || '同步失败')
              }
            }}>立即同步</Button>
          </div>
          <Table
            size="small"
            rowKey="query"
            dataSource={items}
            pagination={{ pageSize: 10, size: 'small', showSizeChanger: false }}
            columns={[
              { title: '搜索词', dataIndex: 'query', ellipsis: true,
                render: v => <Text strong style={{ fontSize: 12 }}>{v}</Text> },
              { title: '决策', width: 80,
                render: (_, r) => {
                  const l = labelOf(r)
                  return <Tag color={l.color} style={{ margin: 0, fontSize: 11 }}>{l.tag}</Tag>
                } },
              { title: '曝光', dataIndex: 'impressions', width: 80, align: 'right',
                sorter: (a, b) => a.impressions - b.impressions,
                render: v => v?.toLocaleString() },
              { title: '点击', dataIndex: 'clicks', width: 70, align: 'right',
                sorter: (a, b) => a.clicks - b.clicks,
                render: v => v?.toLocaleString() },
              { title: 'CTR', dataIndex: 'ctr', width: 70, align: 'right',
                sorter: (a, b) => a.ctr - b.ctr,
                render: v => v ? `${v}%` : '-' },
              { title: '加购', dataIndex: 'add_to_cart', width: 70, align: 'right',
                sorter: (a, b) => a.add_to_cart - b.add_to_cart,
                render: v => v || '-' },
              { title: '加购率', dataIndex: 'atc_rate', width: 80, align: 'right',
                render: v => v ? `${v}%` : '-' },
              { title: '订单', dataIndex: 'orders', width: 70, align: 'right',
                sorter: (a, b) => a.orders - b.orders,
                render: v => v ? <Text strong style={{ color: '#722ed1' }}>{v}</Text> : '-' },
              { title: '转化率', dataIndex: 'cvr', width: 80, align: 'right',
                sorter: (a, b) => a.cvr - b.cvr,
                render: v => {
                  if (!v) return '-'
                  const color = v >= 3 ? '#52c41a' : v >= 1 ? '#faad14' : '#999'
                  return <span style={{ color, fontWeight: 500 }}>{v}%</span>
                } },
              { title: '营收', dataIndex: 'revenue', width: 100, align: 'right',
                sorter: (a, b) => a.revenue - b.revenue,
                defaultSortOrder: 'descend',
                render: v => v > 0 ? <Text strong style={{ color: '#52c41a' }}>¥{v.toLocaleString()}</Text> : '-' },
              { title: '客单价', dataIndex: 'aov', width: 90, align: 'right',
                render: v => v > 0 ? `¥${v}` : '-' },
            ]}
          />
        </div>
      )
    }

    // 兜底：本地广告组+关键词逻辑（其他平台或老路径）
    const adGroupId = getAdGroupIdBySku(sku)
    const adGroup = adGroups.find(g => g.id === adGroupId)
    if (!adGroupId) {
      return (
        <div style={{ padding: 12, background: '#fafafa', borderRadius: 4 }}>
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <span style={{ fontSize: 13 }}>
                该商品未绑定本地广告组。如需管理关键词，请在 <Text strong>广告组</Text> Tab 新建广告组并关联此商品。
              </span>
            }
          />
        </div>
      )
    }
    if (!kws || kws.length === 0) {
      return (
        <div style={{ padding: 12, background: '#fafafa', borderRadius: 4 }}>
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={<span style={{ fontSize: 13 }}>暂无关键词（广告组：{adGroup?.name || adGroupId}）</span>}
          >
            <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => {
              setSelectedGroupId(adGroupId)
              setDetailTab('groups')
              setTimeout(() => { fetchKeywords(adGroupId) }, 0)
              message.info('已跳转到广告组 Tab，可在此添加关键词')
            }}>去添加</Button>
          </Empty>
        </div>
      )
    }
    return (
      <div style={{ padding: 8, background: '#fafafa', borderRadius: 4 }}>
        <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Space size={4}>
            <Text type="secondary" style={{ fontSize: 12 }}>广告组：</Text>
            <Text strong style={{ fontSize: 13 }}>{adGroup?.name || `#${adGroupId}`}</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>· {kws.length} 个关键词</Text>
          </Space>
          <Button size="small" type="link" onClick={() => {
            setSelectedGroupId(adGroupId)
            setDetailTab('groups')
            setTimeout(() => { fetchKeywords(adGroupId) }, 0)
          }}>
            前往广告组管理 →
          </Button>
        </div>
        <Table
          size="small"
          rowKey="id"
          dataSource={kws}
          pagination={false}
          columns={[
            { title: '关键词', dataIndex: 'keyword', key: 'keyword',
              render: (v, r) => r.is_negative
                ? <Space><Tag color="red" style={{ marginRight: 0 }}>否定</Tag>{v}</Space>
                : v },
            { title: '匹配类型', dataIndex: 'match_type', key: 'match_type', width: 120,
              render: v => <Tag>{MATCH_TYPES[v] || v}</Tag> },
            { title: '出价', dataIndex: 'bid', key: 'bid', width: 100,
              render: v => v ? `${v} ₽` : <Text type="secondary">组默认</Text> },
            { title: '状态', dataIndex: 'status', key: 'status', width: 90,
              render: v => v === 'active'
                ? <Badge status="success" text="投放中" />
                : <Badge status="default" text="暂停" /> },
          ]}
        />
      </div>
    )
  }

  if (!searched) {
    return <Card><Empty description="请选择平台和店铺后点击确定" /></Card>
  }

  return (
    <>
      {/* 今日实时汇总 + 异常告警 */}
      <TodaySummaryBar shopId={shopId} />

      {/* 活动列表 */}
      <Card
        title="活动列表"
        size="small"
        style={{ marginBottom: 24 }}
        extra={
          <Space size={8} style={{ alignItems: 'center' }}>
            {lastSyncTime && !syncing && (
              <span style={{ fontSize: 12, color: '#999' }}>
                {(() => {
                  const diff = Math.round((Date.now() - new Date(lastSyncTime).getTime()) / 60000)
                  if (diff < 1) return '刚刚同步'
                  if (diff < 60) return `${diff}分钟前同步`
                  return `${Math.round(diff / 60)}小时前同步`
                })()}
              </span>
            )}
            <Tooltip title={lastSyncTime ? `上次同步：${formatMoscowTime(lastSyncTime)}` : '从平台拉取最新活动列表'}>
              <Button
                size="small"
                icon={<SyncOutlined spin={syncing} />}
                onClick={onSync}
                loading={syncing}
              >
                {syncing ? '同步中' : '同步数据'}
              </Button>
            </Tooltip>
          </Space>
        }
      >
        <Table columns={tableColumns} dataSource={campaigns} rowKey="id" loading={listLoading}
          scroll={{ x: 'max-content' }}
          pagination={{
            current: page, total, pageSize: 20,
            showTotal: (t) => `共 ${t} 个活动`,
            onChange: (p) => { setPage(p); fetchCampaigns(p) },
          }}
          rowClassName={record => record.status !== 'active' ? 'row-paused' : ''}
        />
      </Card>

      <style>{`.row-paused td { opacity: 0.6; }`}</style>

      {/* ==================== 创建活动弹窗 ==================== */}
      <Modal
        title="新建广告活动"
        open={createVisible}
        onOk={handleCreateSubmit}
        onCancel={() => setCreateVisible(false)}
        confirmLoading={createSubmitting}
        destroyOnClose
      >
        <Form form={createForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="platform" label="平台" rules={[{ required: true, message: '请选择平台' }]}>
            <Select options={[
              { value: 'wb', label: 'Wildberries' },
              { value: 'ozon', label: 'Ozon' },
              { value: 'yandex', label: 'Yandex Market' },
            ]} />
          </Form.Item>
          <Form.Item name="shop_id" label="店铺" rules={[{ required: true, message: '请选择店铺' }]}>
            <Select
              options={shops.filter(s => {
                const p = createForm.getFieldValue('platform')
                return p ? s.platform === p : true
              }).map(s => ({ value: s.id, label: s.name }))}
            />
          </Form.Item>
          <Form.Item name="name" label="活动名称" rules={[{ required: true, message: '请输入活动名称' }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="ad_type" label="广告类型" rules={[{ required: true, message: '请选择广告类型' }]}>
            <Select options={Object.entries(AD_TYPES).filter(([k]) => !['banner', 'video'].includes(k)).map(([k, v]) => ({ value: k, label: v.label }))} />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="daily_budget" label="日预算 (₽)">
                <InputNumber min={0} step={100} style={{ width: '100%' }} placeholder="不限" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="total_budget" label="总预算 (₽)">
                <InputNumber min={0} step={100} style={{ width: '100%' }} placeholder="不限" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="status" label="状态" initialValue="draft">
            <Select options={[
              { value: 'draft', label: '草稿' },
              { value: 'active', label: '投放中' },
              { value: 'paused', label: '暂停' },
            ]} />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="start_date" label="开始日期">
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="end_date" label="结束日期">
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      {/* ==================== 编辑活动弹窗 ==================== */}
      <Modal
        title={`编辑广告活动 — ${editingCampaign?.name || ''}`}
        open={editVisible}
        onOk={handleEditSubmit}
        onCancel={() => setEditVisible(false)}
        confirmLoading={editSubmitting}
        destroyOnClose
      >
        <Form form={editForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="name" label="活动名称">
            <Input maxLength={200} placeholder="输入活动名称" />
          </Form.Item>
          <Form.Item name="daily_budget" label="日预算 (₽)">
            <InputNumber min={0} step={100} style={{ width: '100%' }} placeholder="不限" />
          </Form.Item>
          <Form.Item name="total_budget" label="总预算 (₽)">
            <InputNumber min={0} step={100} style={{ width: '100%' }} placeholder="不限" />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select options={[
              { value: 'active', label: '投放中' },
              { value: 'paused', label: '暂停' },
            ]} />
          </Form.Item>
        </Form>
      </Modal>

      {/* ==================== 详情抽屉 ==================== */}
      <Drawer
        title={`广告活动详情 — ${detailData?.name || ''}`}
        open={detailVisible}
        onClose={() => { setDetailVisible(false); setSelectedGroupId(null); setKeywords([]) }}
        width="85%"
        loading={detailLoading}
      >
        {detailData && (
          <Tabs activeKey={detailTab} onChange={setDetailTab} items={[
            {
              key: 'info',
              label: '基本信息',
              children: (() => {
                const pt = detailData.payment_type
                const plat = detailData.platform
                const ptMap = { cpm: { label: 'CPM · 按曝光', color: 'blue' },
                                cpc: { label: 'CPC · 按点击', color: 'green' },
                                cpo: { label: 'CPO · 按订单', color: 'orange' } }
                const ptCfg = ptMap[pt] || { label: pt || '-', color: 'default' }
                const aiSupported = (plat === 'wb' && pt === 'cpm') || (plat === 'ozon' && pt === 'cpc')
                const runDays = detailData.start_date
                  ? dayjs().diff(dayjs(detailData.start_date), 'day') : null
                const budgetVal = campaignBudget
                  ? campaignBudget.total
                  : (detailData.daily_budget != null ? detailData.daily_budget : null)
                return (
                  <div>
                    {/* 顶部 4 卡片：预算 + 平台 + 状态 + 付费类型 */}
                    <Row gutter={12} style={{ marginBottom: 12 }}>
                      <Col span={9}>
                        <Card size="small" style={{
                          background: '#fafbff', borderColor: '#e6edff', height: '100%',
                        }} bodyStyle={{ padding: '12px 14px' }}>
                          <div style={{ fontSize: 12, color: '#999' }}>预算余额</div>
                          <div style={{ fontSize: 22, fontWeight: 600, color: '#1677ff', lineHeight: 1.4, marginTop: 4 }}>
                            {budgetVal != null ? `₽${budgetVal.toLocaleString()}` : '-'}
                          </div>
                          <div style={{ fontSize: 11, color: '#bbb' }}>
                            {campaignBudget ? '实时余额' : '配置预算'}
                          </div>
                        </Card>
                      </Col>
                      <Col span={5}>
                        <Card size="small" style={{ height: '100%' }} bodyStyle={{ padding: '12px 14px' }}>
                          <div style={{ fontSize: 12, color: '#999' }}>平台</div>
                          <div style={{ marginTop: 6 }}>
                            <Tag color={PLATFORMS[detailData.platform]?.color} style={{ fontSize: 12 }}>
                              {PLATFORMS[detailData.platform]?.label}
                            </Tag>
                          </div>
                          <div style={{ fontSize: 11, color: '#bbb', marginTop: 6 }}>
                            {AD_TYPES[detailData.ad_type]?.label || detailData.ad_type}
                          </div>
                        </Card>
                      </Col>
                      <Col span={5}>
                        <Card size="small" style={{ height: '100%' }} bodyStyle={{ padding: '12px 14px' }}>
                          <div style={{ fontSize: 12, color: '#999' }}>状态</div>
                          <div style={{ marginTop: 6 }}>
                            <Badge color={AD_STATUS[detailData.status]?.color}
                              text={<Text style={{ fontSize: 13 }}>{AD_STATUS[detailData.status]?.label || detailData.status}</Text>} />
                          </div>
                          {runDays !== null && (
                            <div style={{ fontSize: 11, color: '#bbb', marginTop: 6 }}>
                              已运行 {runDays} 天
                            </div>
                          )}
                        </Card>
                      </Col>
                      <Col span={5}>
                        <Card size="small" style={{ height: '100%' }} bodyStyle={{ padding: '12px 14px' }}>
                          <div style={{ fontSize: 12, color: '#999' }}>付费方式</div>
                          <div style={{ marginTop: 6 }}>
                            <Tag color={ptCfg.color} style={{ fontSize: 12 }}>{ptCfg.label}</Tag>
                          </div>
                          <div style={{ fontSize: 11, marginTop: 6 }}>
                            {aiSupported
                              ? <Text type="success" style={{ fontSize: 11 }}>AI 调价支持</Text>
                              : <Text type="secondary" style={{ fontSize: 11, color: '#bbb' }}>AI 调价不支持</Text>}
                          </div>
                        </Card>
                      </Col>
                    </Row>

                    {/* AI 调价不支持的活动加提示 */}
                    {!aiSupported && pt && (
                      <Alert
                        style={{ marginBottom: 16 }}
                        type="warning"
                        showIcon
                        message="AI 调价暂不支持此付费类型"
                        description={`当前付费类型 ${pt.toUpperCase()}，AI 调价公式只支持 WB=CPM 和 Ozon=CPC。此活动仅展示数据，不会被 AI 自动调价。`}
                      />
                    )}

                    {/* 流量与转化（仅 WB） */}
                    {plat === 'wb' && (
                      <Card
                        size="small"
                        style={{ marginBottom: 12 }}
                        title={
                          <Space>
                            <span style={{ fontSize: 13 }}>流量与转化</span>
                            {campaignSummaryData?.date_from && (
                              <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
                                {campaignSummaryData.date_from} ~ {campaignSummaryData.date_to}
                              </Text>
                            )}
                          </Space>
                        }
                        extra={
                          <Segmented
                            size="small"
                            value={summaryDays}
                            onChange={reloadCampaignSummary}
                            options={[
                              { label: '近 7 天', value: 7 },
                              { label: '近 14 天', value: 14 },
                              { label: '近 30 天', value: 30 },
                            ]}
                          />
                        }
                      >
                        <Spin spinning={campaignSummaryLoading}>
                          {(() => {
                            const s = campaignSummaryData || {}
                            const cells = [
                              { title: '曝光', value: s.views, suffix: '', color: undefined,
                                tip: '广告被展示给用户的次数' },
                              { title: '点击', value: s.clicks, color: undefined,
                                tip: '用户点击进入商品页的次数' },
                              { title: '加购', value: s.atbs, color: '#1677ff',
                                tip: '点击后加入购物车的次数' },
                              { title: '订单', value: s.orders, color: '#722ed1',
                                tip: '最终成单数' },
                              { title: 'CTR', value: s.ctr, suffix: '%', color: '#1677ff',
                                tip: '点击率 = 点击 ÷ 曝光' },
                              { title: '转化率', value: s.cr, suffix: '%', color: '#13c2c2',
                                tip: '订单 ÷ 点击' },
                              { title: 'CPC', value: s.cpc, suffix: '₽', color: '#fa8c16',
                                tip: '单次点击成本 = 花费 ÷ 点击' },
                              { title: 'ROAS',
                                value: s.roas,
                                suffix: 'x',
                                color: s.roas >= 5 ? '#52c41a' : s.roas >= 2 ? '#faad14' : '#ff4d4f',
                                tip: '广告投资回报率 = 营收 ÷ 花费' },
                            ]
                            return (
                              <>
                                <Row gutter={8}>
                                  {cells.map((c, i) => (
                                    <Col xs={12} sm={6} key={i} style={{ marginBottom: 8 }}>
                                      <Tooltip title={c.tip}>
                                        <div style={{ background: '#fafbff', border: '1px solid #e6edff',
                                                      padding: '10px 12px', borderRadius: 4, cursor: 'help' }}>
                                          <div style={{ fontSize: 11, color: '#999' }}>{c.title}</div>
                                          <div style={{
                                            fontSize: 18, fontWeight: 600, color: c.color || '#1677ff',
                                            marginTop: 2,
                                          }}>
                                            {c.value != null
                                              ? (typeof c.value === 'number' ? c.value.toLocaleString() : c.value)
                                              : '-'}
                                            <span style={{ fontSize: 12, fontWeight: 400, marginLeft: 2, color: '#999' }}>
                                              {c.suffix}
                                            </span>
                                          </div>
                                        </div>
                                      </Tooltip>
                                    </Col>
                                  ))}
                                </Row>
                                <Divider style={{ margin: '8px 0' }} />
                                <Row gutter={16}>
                                  <Col span={12}>
                                    <Space>
                                      <Text type="secondary" style={{ fontSize: 12 }}>花费</Text>
                                      <Text strong style={{ fontSize: 14 }}>
                                        ₽{(s.spend || 0).toLocaleString()}
                                      </Text>
                                    </Space>
                                  </Col>
                                  <Col span={12}>
                                    <Space>
                                      <Text type="secondary" style={{ fontSize: 12 }}>营收</Text>
                                      <Text strong style={{ fontSize: 14 }}>
                                        ₽{(s.revenue || 0).toLocaleString()}
                                      </Text>
                                    </Space>
                                  </Col>
                                </Row>
                              </>
                            )
                          })()}
                        </Spin>
                      </Card>
                    )}

                    {/* 详细信息 */}
                    <Card size="small" title={<span style={{ fontSize: 13 }}>活动详情</span>} bodyStyle={{ padding: 0 }}>
                      <Descriptions
                        column={2} bordered size="small"
                        labelStyle={{ width: 120, background: '#fafbff', color: '#666' }}
                      >
                        <Descriptions.Item label="活动名称" span={2}>
                          <Text strong>{detailData.name}</Text>
                        </Descriptions.Item>
                        <Descriptions.Item label="活动 ID">
                          <Text code style={{ fontSize: 12 }}>{detailData.platform_campaign_id || '-'}</Text>
                        </Descriptions.Item>
                        <Descriptions.Item label="总预算">
                          {detailData.total_budget != null
                            ? <Text strong>₽{detailData.total_budget?.toLocaleString()}</Text>
                            : <Text type="secondary">不限</Text>}
                        </Descriptions.Item>
                        <Descriptions.Item label="投放周期" span={2}>
                          {detailData.start_date
                            ? <>
                                <Text>{detailData.start_date} ~ {detailData.end_date || '至今'}</Text>
                                {runDays !== null && (
                                  <Text type="secondary" style={{ marginLeft: 12, fontSize: 12 }}>
                                    （已运行 {runDays} 天）
                                  </Text>
                                )}
                              </>
                            : <Text type="secondary">未设置</Text>}
                        </Descriptions.Item>
                      </Descriptions>
                    </Card>
                  </div>
                )
              })(),
            },
            {
              key: 'products',
              label: `商品出价 (${campaignProducts.length})`,
              children: (
                <div>
                  {/* 当日实时汇总（仅 WB；几小时延迟，5 分钟缓存） */}
                  {detailData.platform === 'wb' && (
                    <Card
                      size="small"
                      style={{ marginBottom: 12, background: '#fafbff', borderColor: '#e6edff' }}
                      bodyStyle={{ padding: '10px 14px' }}
                    >
                      <Spin spinning={todayLoading}>
                        <Row gutter={16} align="middle" wrap={false}>
                          <Col flex="none">
                            <Space size={6}>
                              <Text strong style={{ fontSize: 13 }}>今日</Text>
                              <Tooltip title="WB fullstats v3 数据有几小时延迟，早上常空，下午陆续就位。点刷新强制重新拉。">
                                <Text type="secondary" style={{ fontSize: 11, cursor: 'help' }}>
                                  {todaySummary?.today_date || '-'}
                                </Text>
                              </Tooltip>
                            </Space>
                          </Col>
                          <Col flex="auto">
                            <Row gutter={16}>
                              <Col span={4}>
                                <div style={{ fontSize: 11, color: '#999' }}>花费</div>
                                <div style={{ fontSize: 16, fontWeight: 600 }}>
                                  ₽{(todaySummary?.spend ?? 0).toLocaleString()}
                                </div>
                              </Col>
                              <Col span={4}>
                                <div style={{ fontSize: 11, color: '#999' }}>订单</div>
                                <div style={{ fontSize: 16, fontWeight: 600, color: '#52c41a' }}>
                                  {todaySummary?.orders ?? 0}
                                </div>
                              </Col>
                              <Col span={4}>
                                <div style={{ fontSize: 11, color: '#999' }}>曝光</div>
                                <div style={{ fontSize: 16, fontWeight: 600 }}>
                                  {(todaySummary?.views ?? 0).toLocaleString()}
                                </div>
                              </Col>
                              <Col span={4}>
                                <div style={{ fontSize: 11, color: '#999' }}>点击</div>
                                <div style={{ fontSize: 16, fontWeight: 600 }}>
                                  {todaySummary?.clicks ?? 0}
                                </div>
                              </Col>
                              <Col span={4}>
                                <div style={{ fontSize: 11, color: '#999' }}>ROAS</div>
                                <div style={{
                                  fontSize: 16, fontWeight: 600,
                                  color: (todaySummary?.roas ?? 0) >= 2 ? '#52c41a'
                                       : (todaySummary?.roas ?? 0) > 0 ? '#faad14' : '#999',
                                }}>
                                  {todaySummary?.roas ? `${todaySummary.roas}x` : '-'}
                                </div>
                              </Col>
                              <Col span={4}>
                                <div style={{ fontSize: 11, color: '#999' }}>预算余额</div>
                                <div style={{ fontSize: 16, fontWeight: 600, color: '#1677ff' }}>
                                  {todaySummary?.budget_remaining != null
                                    ? `₽${todaySummary.budget_remaining.toLocaleString()}`
                                    : '-'}
                                </div>
                              </Col>
                            </Row>
                          </Col>
                          <Col flex="none">
                            <Button size="small" icon={<SyncOutlined spin={todayLoading} />}
                              onClick={() => loadTodaySummary(detailData.id, true)}>
                              刷新
                            </Button>
                          </Col>
                        </Row>
                      </Spin>
                    </Card>
                  )}
                  {/* 自动屏蔽托管（仅 WB） */}
                  {detailData.platform === 'wb' && (
                    <Card
                      size="small"
                      style={{ marginBottom: 12, background: '#fafbff', borderColor: '#e6edff' }}
                      bodyStyle={{ padding: '10px 14px' }}
                    >
                      <Row align="middle" gutter={12} wrap={false}>
                        <Col flex="none">
                          <Space size={8}>
                            <Text strong style={{ fontSize: 13 }}>自动屏蔽托管</Text>
                            <Switch
                              size="small"
                              checked={!!autoExcludeCfg?.enabled}
                              loading={autoExcludeBusy}
                              onChange={handleToggleAutoExclude}
                            />
                          </Space>
                        </Col>
                        <Col flex="auto" style={{ paddingLeft: 16 }}>
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            规则复用「关键词效能规则」waste 档（
                            <a onClick={() => setRulesDrawerOpen(true)}>查看/调整</a>
                            ），跳过白名单 + 已屏蔽词
                          </Text>
                          <div style={{ marginTop: 4, fontSize: 12 }}>
                            <Text type="secondary">本月已屏蔽 </Text>
                            <Text strong>{autoExcludeCfg?.month_excluded_total ?? 0}</Text>
                            <Text type="secondary"> 个词 · 估算节省 </Text>
                            <Text strong>¥{(autoExcludeCfg?.month_saved_estimated ?? 0).toLocaleString()}</Text>
                            {autoExcludeCfg?.last_run_at && (
                              <Text type="secondary" style={{ marginLeft: 12, fontSize: 12 }}>
                                · 最近运行 {formatMoscowTime(autoExcludeCfg.last_run_at)}
                              </Text>
                            )}
                          </div>
                        </Col>
                        <Col flex="none">
                          <Space size={6}>
                            <Button size="small" onClick={handleViewAutoExcludeLogs}>查看详情</Button>
                            <Button size="small" type="primary" icon={<SyncOutlined spin={autoExcludeBusy} />}
                              loading={autoExcludeBusy} onClick={handleRunAutoExcludeNow}>
                              立即跑一次
                            </Button>
                          </Space>
                        </Col>
                      </Row>
                    </Card>
                  )}
                  <Alert
                    type="info"
                    showIcon
                    style={{ marginBottom: 12 }}
                    message={
                      detailData.platform === 'ozon'
                        ? '点击出价可修改；点击商品行可展开查看该商品的关键词。'
                        : 'WB 同时改搜索+推荐 CPM（与 WB 后台一致），未启用的 placement 会被跳过。点击商品行可展开关键词。'
                    }
                  />
                  {campaignProducts.length > 0 ? (
                    detailData.platform === 'ozon' ? (
                      <Table
                        size="middle"
                        dataSource={campaignProducts}
                        rowKey="sku"
                        loading={productsLoading}
                        pagination={false}
                        expandable={{
                          expandedRowKeys: expandedSkuKeys,
                          onExpand: handleProductRowExpand,
                          expandedRowRender: record => renderKeywordsExpandedRow(record),
                          rowExpandable: () => true,
                        }}
                        columns={[
                          {
                            title: '商品', key: 'product',
                            render: (_, record) => renderProductCell(record),
                          },
                          {
                            title: '出价 (₽)', dataIndex: 'bid', key: 'bid', width: 180,
                            render: (v, record) => {
                              const displayBid = Math.round(Number(v || 0) / 1000000)
                              if (editingBid?.sku === record.sku) {
                                return (
                                  <Space>
                                    <InputNumber size="small" value={newBidValue} onChange={setNewBidValue}
                                      min={1} step={1} style={{ width: 80 }} addonAfter="₽" />
                                    <Button size="small" type="primary" loading={bidUpdating} onClick={handleUpdateBid}>保存</Button>
                                    <Button size="small" onClick={() => setEditingBid(null)}>取消</Button>
                                  </Space>
                                )
                              }
                              return (
                                <Tooltip title="点击修改出价">
                                  <a onClick={() => { setEditingBid(record); setNewBidValue(displayBid) }}
                                    style={{ fontSize: 16, fontWeight: 600 }}>
                                    {displayBid} <span style={{ fontSize: 12, color: '#999' }}>₽</span>
                                  </a>
                                </Tooltip>
                              )
                            },
                          },
                        ]}
                      />
                    ) : (
                      // WB 平台：per-SKU 出价表格（搜索 / 推荐双 CPM）
                      <Table
                        size="middle"
                        dataSource={campaignProducts}
                        rowKey="sku"
                        loading={productsLoading}
                        pagination={false}
                        expandable={{
                          expandedRowKeys: expandedSkuKeys,
                          onExpand: handleProductRowExpand,
                          expandedRowRender: record => renderKeywordsExpandedRow(record),
                          rowExpandable: () => true,
                        }}
                        columns={[
                          {
                            title: '商品', key: 'product',
                            render: (_, record) => renderProductCell(record),
                          },
                          { title: '搜索 CPM', dataIndex: 'bid_search', key: 'bid_search', width: 110,
                            render: v => <Text strong>{Number(v || 0).toLocaleString()} ₽</Text> },
                          { title: '推荐 CPM', dataIndex: 'bid_recommendations', key: 'bid_recommendations', width: 110,
                            render: v => <Text strong>{Number(v || 0).toLocaleString()} ₽</Text> },
                          {
                            title: '修改 CPM', key: 'edit', width: 260,
                            render: (_, record) => {
                              if (editingBid?.sku === record.sku) {
                                return (
                                  <Space>
                                    <InputNumber
                                      size="small"
                                      value={newBidValue}
                                      onChange={setNewBidValue}
                                      min={1} step={1}
                                      style={{ width: 90 }}
                                      addonAfter="₽"
                                      autoFocus
                                    />
                                    <Button size="small" type="primary" loading={bidUpdating} onClick={handleUpdateBid}>
                                      保存
                                    </Button>
                                    <Button size="small" onClick={() => setEditingBid(null)}>取消</Button>
                                  </Space>
                                )
                              }
                              return (
                                <Tooltip title="同时修改搜索和推荐 CPM（与 WB 后台一致）">
                                  <Button
                                    size="small"
                                    type="link"
                                    icon={<EditOutlined />}
                                    onClick={() => {
                                      setEditingBid(record)
                                      setNewBidValue(Number(record.bid_search || 0))
                                    }}
                                  >
                                    修改
                                  </Button>
                                </Tooltip>
                              )
                            },
                          },
                        ]}
                      />
                    )
                  ) : (
                    <Empty description={productsLoading ? '加载中...' : '暂无商品数据'} />
                  )}
                </div>
              ),
            },
            // 广告组 Tab：WB 隐藏（WB 没有"组"概念，活动级出价 + 关键词在商品出价 Tab）
            ...(detailData.platform === 'wb' ? [] : [{
              key: 'groups',
              label: `广告组 (${adGroups.length})`,
              children: (
                <div>
                  <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between' }}>
                    <Text strong>广告组列表</Text>
                    <Button type="primary" size="small" icon={<PlusOutlined />} onClick={handleCreateGroup}>新建广告组</Button>
                  </div>
                  <Table size="small" columns={groupColumns} dataSource={adGroups} rowKey="id" loading={groupsLoading} pagination={false} />

                  {selectedGroupId && (
                    <div style={{ marginTop: 24 }}>
                      <Divider />
                      <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between' }}>
                        <Text strong>关键词 — {adGroups.find(g => g.id === selectedGroupId)?.name}</Text>
                        <Space>
                          <Button size="small" icon={<PlusOutlined />} onClick={handleCreateKeyword}>添加</Button>
                          <Button size="small" onClick={handleBatchKeywords}>批量添加</Button>
                        </Space>
                      </div>
                      <Table size="small" columns={keywordColumns} dataSource={keywords} rowKey="id" loading={keywordsLoading} pagination={false} />
                    </div>
                  )}
                </div>
              ),
            }]),
          ]} />
        )}
      </Drawer>


      {/* ==================== 广告组 表单弹窗 ==================== */}
      <Modal
        title={editingGroup ? '编辑广告组' : '新建广告组'}
        open={groupFormVisible}
        onOk={handleGroupSubmit}
        onCancel={() => setGroupFormVisible(false)}
        confirmLoading={groupSubmitting}
        destroyOnClose
      >
        <Form form={groupForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="name" label="广告组名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="bid" label="出价 (₽)">
            <InputNumber min={0} step={0.5} style={{ width: '100%' }} placeholder="默认出价" />
          </Form.Item>
          <Form.Item name="listing_id" label="关联商品ID">
            <InputNumber min={0} style={{ width: '100%' }} placeholder="可选" />
          </Form.Item>
          <Form.Item name="status" label="状态" initialValue="active">
            <Select options={[
              { value: 'active', label: '投放中' },
              { value: 'paused', label: '暂停' },
            ]} />
          </Form.Item>
        </Form>
      </Modal>

      {/* ==================== 关键词 单个表单 ==================== */}
      <Modal
        title={editingKeyword ? '编辑关键词' : '添加关键词'}
        open={kwFormVisible}
        onOk={handleKwSubmit}
        onCancel={() => setKwFormVisible(false)}
        confirmLoading={kwSubmitting}
        destroyOnClose
      >
        <Form form={kwForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="keyword" label="关键词" rules={[{ required: true, message: '请输入关键词' }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="match_type" label="匹配类型" initialValue="broad">
                <Select options={Object.entries(MATCH_TYPES).map(([k, v]) => ({ value: k, label: v }))} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="bid" label="出价 (₽)">
                <InputNumber min={0} step={0.5} style={{ width: '100%' }} placeholder="使用组出价" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="is_negative" label="关键词类型" initialValue={0}>
            <Select options={[
              { value: 0, label: '正向关键词' },
              { value: 1, label: '否定关键词' },
            ]} />
          </Form.Item>
          <Form.Item name="status" label="状态" initialValue="active">
            <Select options={[
              { value: 'active', label: '投放中' },
              { value: 'paused', label: '暂停' },
            ]} />
          </Form.Item>
        </Form>
      </Modal>

      {/* ==================== 关键词 批量添加 ==================== */}
      <Modal
        title="批量添加关键词"
        open={kwBatchVisible}
        onOk={handleBatchKwSubmit}
        onCancel={() => setKwBatchVisible(false)}
        confirmLoading={kwSubmitting}
        destroyOnClose
      >
        <Form form={kwBatchForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="keywords_text" label="关键词（每行一个）" rules={[{ required: true, message: '请输入关键词' }]}>
            <TextArea rows={6} placeholder="每行输入一个关键词&#10;例如：&#10;连衣裙&#10;夏季连衣裙&#10;女装连衣裙" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="match_type" label="匹配类型" initialValue="broad">
                <Select options={Object.entries(MATCH_TYPES).map(([k, v]) => ({ value: k, label: v }))} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="bid" label="统一出价 (₽)">
                <InputNumber min={0} step={0.5} style={{ width: '100%' }} placeholder="使用组出价" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="is_negative" label="关键词类型" initialValue={0}>
            <Select options={[
              { value: 0, label: '正向关键词' },
              { value: 1, label: '否定关键词' },
            ]} />
          </Form.Item>
        </Form>
      </Modal>

      {/* ==================== ROI告警弹窗 ==================== */}
      <Modal
        title="ROI异常告警"
        open={alertsVisible}
        onCancel={() => setAlertsVisible(false)}
        footer={null}
        width={650}
      >
        <List
          loading={alertsLoading}
          dataSource={alerts}
          locale={{ emptyText: '暂无告警记录' }}
          pagination={{
            current: alertsPage,
            total: alertsTotal,
            pageSize: 10,
            onChange: (p) => fetchAlerts(p),
            size: 'small',
          }}
          renderItem={(item) => (
            <List.Item>
              <List.Item.Meta
                title={
                  <Space>
                    {item.is_read ? null : <Badge status="error" />}
                    <Text strong>{item.title}</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>{item.sent_at}</Text>
                  </Space>
                }
                description={
                  <pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: 13, color: '#555' }}>
                    {item.content}
                  </pre>
                }
              />
            </List.Item>
          )}
        />
      </Modal>

      {/* ==================== 告警配置弹窗 ==================== */}
      <Modal
        title="告警阈值配置"
        open={configVisible}
        onOk={handleConfigSubmit}
        onCancel={() => setConfigVisible(false)}
        confirmLoading={configSubmitting}
      >
        <Form form={configForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="acos_warning" label="ACOS 警告阈值 (%)">
            <InputNumber min={0} max={100} step={5} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="acos_critical" label="ACOS 严重阈值 (%)">
            <InputNumber min={0} max={100} step={5} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="roas_warning" label="ROAS 警告阈值（低于此值触发）">
            <InputNumber min={0} step={0.5} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="budget_usage_threshold" label="预算使用率阈值（0~1，如0.8=80%）">
            <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="roas_critical_with_budget" label="预算超标时 ROAS 严重阈值">
            <InputNumber min={0} step={0.5} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      <EfficiencyRulesDrawer
        open={rulesDrawerOpen}
        onClose={() => setRulesDrawerOpen(false)}
        onSaved={loadExcludeRules}
      />

      <Drawer
        title={`🤖 自动屏蔽日志 — ${detailData?.name || ''}（最近 30 天）`}
        open={autoExcludeLogsDrawer}
        onClose={() => setAutoExcludeLogsDrawer(false)}
        width={720}
      >
        <Table
          size="small"
          loading={autoExcludeLogsLoading}
          dataSource={autoExcludeLogs}
          rowKey={(r, i) => `${r.excluded_at}_${r.keyword}_${i}`}
          pagination={{ pageSize: 30, size: 'small' }}
          columns={[
            { title: '屏蔽时间', dataIndex: 'excluded_at', width: 150,
              render: v => formatMoscowTime(v) },
            { title: '关键词', dataIndex: 'keyword', ellipsis: true },
            { title: 'nm_id', dataIndex: 'nm_id', width: 110 },
            { title: '触发理由', dataIndex: 'reason', width: 220, ellipsis: true,
              render: v => <Text type="secondary" style={{ fontSize: 12 }}>{v || '-'}</Text> },
            { title: '估算月省', dataIndex: 'saved_per_month', width: 110, align: 'right',
              render: v => <Text strong style={{ color: '#52c41a' }}>¥{v?.toLocaleString() || 0}</Text> },
          ]}
        />
      </Drawer>
    </>
  )
}

export default AdsOverview
