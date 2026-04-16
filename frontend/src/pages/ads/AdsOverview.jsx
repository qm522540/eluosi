import { useState, useEffect, useCallback } from 'react'
import {
  Typography, Card, Table, Button, Tag, Space, Select, Row, Col,
  Statistic, Modal, Form, Input, InputNumber, message, DatePicker, Tooltip, Badge, Empty,
  Popconfirm, Tabs, Alert, Drawer, Descriptions, List, Divider, Progress, Checkbox, Popover,
} from 'antd'
import {
  SearchOutlined, EditOutlined, EyeOutlined, SyncOutlined, PlusOutlined,
  DeleteOutlined, SettingOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import {
  getCampaigns, getCampaign, createCampaign, updateCampaign, deleteCampaign,
  getAdGroups, createAdGroup, updateAdGroup, deleteAdGroup,
  getKeywords, createKeyword, batchCreateKeywords, updateKeyword, deleteKeyword,
  getAdStats, getAdSummary,
  exportAdStats, getAlerts, getAlertConfig, updateAlertConfig,
  getCampaignProducts, updateCampaignBid, getCampaignBudget,
  getShopSummary,
} from '@/api/ads'
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

const TodaySummaryCards = ({ shopId }) => {
  const [summary, setSummary] = useState(null)

  useEffect(() => {
    if (!shopId) return
    getShopSummary(shopId).then(res => setSummary(res.data)).catch(() => {})
  }, [shopId])

  if (!summary) return null

  const cards = [
    { label: '今日总花费', value: `₽${(summary.today_spend || 0).toLocaleString()}`, sub: `昨日 ₽${(summary.yesterday_spend || 0).toLocaleString()}` },
    { label: '店铺整体ROAS', value: `${summary.today_roas || '-'}x`, sub: `7天均值 ${summary.avg_roas_7d || '-'}x`, color: (summary.today_roas || 0) >= 3 ? '#52c41a' : (summary.today_roas || 0) >= 1.8 ? '#faad14' : '#ff4d4f' },
    { label: '今日总订单', value: summary.today_orders || '-', sub: `7天均值 ${summary.avg_orders_7d || '-'}单/天` },
    { label: '投放中活动', value: `${summary.active_count || 0}个`, sub: `共${summary.total_count || 0}个活动` },
  ]

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
      {cards.map((card, i) => (
        <div key={i} style={{ background: '#fafafa', borderRadius: 8, padding: '12px 16px' }}>
          <div style={{ fontSize: 13, color: '#999', marginBottom: 4 }}>{card.label}</div>
          <div style={{ fontSize: 22, fontWeight: 500, color: card.color || '#333' }}>{card.value}</div>
          <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>{card.sub}</div>
        </div>
      ))}
    </div>
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
    try {
      const res = await getCampaign(id)
      setDetailData(res.data)
      fetchAdGroups(id)
      getCampaignBudget(id).then(r => setCampaignBudget(r.data)).catch(err => console.warn('预算加载失败', err))
      fetchCampaignProducts(id)
    } catch {
      message.error('获取广告详情失败')
    } finally {
      setDetailLoading(false)
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
  }

  const PLATFORM_DEFAULT_COLS = {
    ozon: ['campaign_name', 'status', 'today_spend', 'today_roas', 'today_orders', 'avg_roas_7d', 'roas_trend', 'budget_used_pct', 'daily_budget'],
    wb: ['campaign_name', 'status', 'today_spend', 'today_roas', 'today_orders', 'avg_roas_7d', 'spend_7d', 'budget_used_pct'],
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

  if (!searched) {
    return <Card><Empty description="请选择平台和店铺后点击确定" /></Card>
  }

  return (
    <>
      {/* 顶部汇总卡片 */}
      <TodaySummaryCards shopId={shopId} />

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
            <Tooltip title={lastSyncTime ? `上次同步：${new Date(lastSyncTime).toLocaleString()}` : '从平台拉取最新活动列表'}>
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
        width={900}
        loading={detailLoading}
      >
        {detailData && (
          <Tabs activeKey={detailTab} onChange={setDetailTab} items={[
            {
              key: 'info',
              label: '基本信息',
              children: (
                <div>
                  <Card size="small" style={{ marginBottom: 16, background: '#f6ffed', borderColor: '#b7eb8f' }}>
                    <Row align="middle">
                      <Col span={8}>
                        <Text type="secondary">预算余额</Text>
                        <div style={{ fontSize: 24, fontWeight: 600, color: '#52c41a' }}>
                          {campaignBudget ? `${campaignBudget.total?.toLocaleString()} ₽` : detailData.daily_budget != null ? `${detailData.daily_budget?.toLocaleString()} ₽` : '-'}
                        </div>
                      </Col>
                      <Col span={16}>
                        <Descriptions column={2} size="small" style={{ marginBottom: 0 }}>
                          <Descriptions.Item label="平台">
                            <Tag color={PLATFORMS[detailData.platform]?.color}>{PLATFORMS[detailData.platform]?.label}</Tag>
                          </Descriptions.Item>
                          <Descriptions.Item label="状态">
                            <Badge color={AD_STATUS[detailData.status]?.color} text={AD_STATUS[detailData.status]?.label || detailData.status} />
                          </Descriptions.Item>
                          <Descriptions.Item label="广告类型">{AD_TYPES[detailData.ad_type]?.label || detailData.ad_type}</Descriptions.Item>
                          <Descriptions.Item label="活动ID">{detailData.platform_campaign_id || '-'}</Descriptions.Item>
                        </Descriptions>
                      </Col>
                    </Row>
                  </Card>
                  <Descriptions column={2} bordered size="small">
                    <Descriptions.Item label="名称">{detailData.name}</Descriptions.Item>
                    <Descriptions.Item label="总预算">{detailData.total_budget != null ? `₽${detailData.total_budget}` : '不限'}</Descriptions.Item>
                    <Descriptions.Item label="开始日期">{detailData.start_date || '-'}</Descriptions.Item>
                    <Descriptions.Item label="结束日期">{detailData.end_date || '-'}</Descriptions.Item>
                  </Descriptions>
                </div>
              ),
            },
            {
              key: 'products',
              label: `商品出价 (${campaignProducts.length})`,
              children: (
                <div>
                  <div style={{ marginBottom: 12 }}>
                    <Text type="secondary">
                      {detailData.platform === 'ozon'
                        ? '以下是该活动关联的商品及出价，点击出价可修改。'
                        : 'WB活动按搜索 / 推荐两个广告位分别定价，点击「修改」可同时设置两个广告位的 CPM（与 WB 后台一致）。如果活动未启动或 placement 未启用，修改会被 WB 拒绝。'}
                    </Text>
                  </div>
                  {campaignProducts.length > 0 ? (
                    detailData.platform === 'ozon' ? (
                      <Table size="small" dataSource={campaignProducts} rowKey="sku" loading={productsLoading} pagination={false}
                        columns={[
                          { title: 'SKU', dataIndex: 'sku', key: 'sku', width: 130 },
                          {
                            title: '商品', key: 'product', ellipsis: { showTitle: false },
                            render: (_, record) => (
                              <Space>
                                {record.image ? (
                                  <img src={record.image} alt="" style={{ width: 40, height: 40, objectFit: 'cover', borderRadius: 4 }} />
                                ) : (
                                  <div style={{ width: 40, height: 40, background: '#f0f0f0', borderRadius: 4, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#ccc', fontSize: 12 }}>无图</div>
                                )}
                                <Tooltip title={record.title} placement="topLeft">
                                  <Text ellipsis style={{ maxWidth: 350 }}>{record.title || '-'}</Text>
                                </Tooltip>
                              </Space>
                            ),
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
                                <a onClick={() => { setEditingBid(record); setNewBidValue(displayBid) }}>
                                  {displayBid} ₽
                                </a>
                              )
                            },
                          },
                        ]}
                      />
                    ) : (
                      // WB 平台：per-SKU 出价表格（搜索 / 推荐双 CPM）
                      // 一个输入框同时改两个广告位（对齐 WB 后台 UI 行为）
                      <Table size="small" dataSource={campaignProducts} rowKey="sku" loading={productsLoading} pagination={false}
                        columns={[
                          { title: 'SKU (nm_id)', dataIndex: 'sku', key: 'sku', width: 140 },
                          { title: '类目', dataIndex: 'subject_name', key: 'subject_name', width: 160,
                            render: v => v || '-' },
                          { title: '搜索 CPM (₽)', dataIndex: 'bid_search', key: 'bid_search', width: 130,
                            render: v => `${Number(v || 0).toLocaleString()} ₽` },
                          { title: '推荐 CPM (₽)', dataIndex: 'bid_recommendations', key: 'bid_recommendations', width: 130,
                            render: v => `${Number(v || 0).toLocaleString()} ₽` },
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
                                    onClick={() => {
                                      setEditingBid(record)
                                      // 用 search 值作为初始值（实测两个 placement 通常相同）
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
            {
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
            },
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
    </>
  )
}

export default AdsOverview
