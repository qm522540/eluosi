import { useState, useEffect, useCallback } from 'react'
import {
  Typography, Card, Table, Button, Tag, Space, Select, Row, Col,
  Statistic, Modal, Form, Input, InputNumber, message, DatePicker, Tooltip, Badge, Empty,
  Popconfirm, Tabs, Alert, Drawer, Descriptions, List, Divider,
} from 'antd'
import {
  SearchOutlined, EditOutlined, EyeOutlined, SyncOutlined, PlusOutlined,
  DeleteOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import {
  getCampaigns, getCampaign, createCampaign, updateCampaign, deleteCampaign,
  getAdGroups, createAdGroup, updateAdGroup, deleteAdGroup,
  getKeywords, createKeyword, batchCreateKeywords, updateKeyword, deleteKeyword,
  getAdStats, getAdSummary, syncAds,
  getOptimizeSuggestions, applyBidSuggestions,
  exportAdStats, getAlerts, getAlertConfig, updateAlertConfig,
  getCampaignProducts, updateCampaignBid, getCampaignBudget,
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

const AdsOverview = ({ shopId, platform, shops, searched }) => {
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
  const [syncing, setSyncing] = useState(false)

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

  // 出价优化
  const [optimizeVisible, setOptimizeVisible] = useState(false)
  const [optimizeLoading, setOptimizeLoading] = useState(false)
  const [optimizeSuggestions, setOptimizeSuggestions] = useState(null)
  const [optimizeForm] = Form.useForm()
  const [applyingBids, setApplyingBids] = useState(false)

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

  // ==================== 同步 ====================

  const handleSync = async () => {
    setSyncing(true)
    try {
      await syncAds()
      message.success('同步任务已提交，数据将在1-2分钟内更新')
      if (searched) {
        setTimeout(() => { fetchCampaigns(); fetchSummary(); fetchStats() }, 10000)
      }
    } catch (err) {
      message.error(err.message || '同步失败')
    } finally {
      setSyncing(false)
    }
  }

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
      const apiBid = newBidValue * 1000000
      await updateCampaignBid(detailData.id, { sku: editingBid.sku, bid: String(apiBid) })
      message.success('出价修改成功')
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

  // ==================== 出价优化 ====================

  const handleOptimize = (campaignId) => {
    optimizeForm.resetFields()
    optimizeForm.setFieldValue('campaign_id', campaignId)
    setOptimizeSuggestions(null)
    setOptimizeVisible(true)
  }

  const handleGetSuggestions = async () => {
    try {
      const values = await optimizeForm.validateFields()
      setOptimizeLoading(true)
      const res = await getOptimizeSuggestions(values)
      setOptimizeSuggestions(res.data)
    } catch (err) {
      if (err.errorFields) return
      message.error(err.message || '获取优化建议失败')
    } finally {
      setOptimizeLoading(false)
    }
  }

  const handleApplyBids = async () => {
    if (!optimizeSuggestions?.suggestions?.length) return
    setApplyingBids(true)
    try {
      await applyBidSuggestions(optimizeSuggestions.suggestions)
      message.success('出价已批量更新')
      setOptimizeVisible(false)
      if (detailData) fetchAdGroups(detailData.id)
    } catch (err) {
      message.error(err.message || '应用出价失败')
    } finally {
      setApplyingBids(false)
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

  // ==================== 表格列 ====================

  const columns = [
    {
      title: '活动ID',
      dataIndex: 'platform_campaign_id',
      key: 'platform_campaign_id',
      width: 140,
      ellipsis: true,
      render: (text, record) => (
        <a onClick={() => handleDetail(record.id)}>{text || record.id}</a>
      ),
    },
    {
      title: '活动名称',
      dataIndex: 'name',
      key: 'name',
      width: 220,
      ellipsis: { showTitle: false },
      render: (text) => <Tooltip title={text} placement="topLeft">{text}</Tooltip>,
    },
    {
      title: '平台',
      dataIndex: 'platform',
      key: 'platform',
      width: 130,
      render: (p) => {
        const info = PLATFORMS[p]
        return info ? <Tag color={info.color}>{info.label}</Tag> : p
      },
    },
    {
      title: '广告类型',
      dataIndex: 'ad_type',
      key: 'ad_type',
      width: 110,
      render: (t) => AD_TYPES[t]?.label || t,
    },
    {
      title: '预算余额',
      dataIndex: 'daily_budget',
      key: 'daily_budget',
      width: 100,
      align: 'right',
      render: (v) => v != null ? `₽${v.toLocaleString()}` : '-',
    },
    {
      title: 'CTR',
      dataIndex: 'ctr',
      key: 'ctr',
      width: 80,
      align: 'right',
      render: (v) => v ? `${v}%` : '0%',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (s) => {
        const info = AD_STATUS[s]
        return info ? <Badge color={info.color} text={info.label} /> : s
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 220,
      render: (_, record) => (
        <Space size="small">
          <Tooltip title="查看详情">
            <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => handleDetail(record.id)}>
              详情
            </Button>
          </Tooltip>
          <Tooltip title="调整预算/状态">
            <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>
              编辑
            </Button>
          </Tooltip>
          <Tooltip title="出价优化">
            <Button type="link" size="small" icon={<ThunderboltOutlined />} onClick={() => handleOptimize(record.id)} />
          </Tooltip>
          <Popconfirm title="确定删除此广告活动？关联的广告组、关键词和统计数据将一并删除。" onConfirm={() => handleDelete(record.id)} okText="确定" cancelText="取消">
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
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
      {/* 活动列表 */}
      <Card title="活动列表" size="small" style={{ marginBottom: 24 }}>
        <Table columns={columns} dataSource={campaigns} rowKey="id" loading={listLoading}
          pagination={{
            current: page, total, pageSize: 20,
            showTotal: (t) => `共 ${t} 个活动`,
            onChange: (p) => { setPage(p); fetchCampaigns(p) },
          }}
        />
      </Card>

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
                      {detailData.platform === 'ozon' ? '以下是该活动关联的商品及出价，点击出价可修改。' : 'WB暂不支持通过API获取商品列表。'}
                    </Text>
                  </div>
                  {campaignProducts.length > 0 ? (
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

      {/* ==================== 出价优化弹窗 ==================== */}
      <Modal
        title="出价优化"
        open={optimizeVisible}
        onCancel={() => setOptimizeVisible(false)}
        width={700}
        footer={optimizeSuggestions?.suggestions?.length > 0 ? [
          <Button key="cancel" onClick={() => setOptimizeVisible(false)}>取消</Button>,
          <Button key="apply" type="primary" loading={applyingBids} onClick={handleApplyBids}>应用全部建议</Button>,
        ] : null}
      >
        <Form form={optimizeForm} layout="inline" style={{ marginBottom: 16 }}>
          <Form.Item name="campaign_id" hidden><Input /></Form.Item>
          <Form.Item name="target_roas" label="目标ROAS" initialValue={2.0}>
            <InputNumber min={0.1} step={0.1} style={{ width: 100 }} />
          </Form.Item>
          <Form.Item name="max_bid_increase" label="最大加价%" initialValue={30}>
            <InputNumber min={0} max={100} style={{ width: 80 }} />
          </Form.Item>
          <Form.Item name="max_bid_decrease" label="最大降价%" initialValue={30}>
            <InputNumber min={0} max={100} style={{ width: 80 }} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" loading={optimizeLoading} onClick={handleGetSuggestions}>获取建议</Button>
          </Form.Item>
        </Form>

        {optimizeSuggestions && (
          <>
            <Alert
              message={`活动: ${optimizeSuggestions.campaign_name} | 目标ROAS: ${optimizeSuggestions.target_roas}`}
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
            />
            {optimizeSuggestions.suggestions.length === 0 ? (
              <Empty description="没有需要调整的广告组（可能无近期数据或无出价）" />
            ) : (
              <Table
                size="small"
                dataSource={optimizeSuggestions.suggestions}
                rowKey="group_id"
                pagination={false}
                columns={[
                  { title: '广告组', dataIndex: 'group_name', key: 'group_name', ellipsis: true },
                  { title: '当前出价', dataIndex: 'current_bid', key: 'current_bid', width: 90, render: v => `₽${v}` },
                  {
                    title: '建议出价', dataIndex: 'suggested_bid', key: 'suggested_bid', width: 90,
                    render: (v, r) => <Text style={{ color: r.action === 'increase' ? '#52c41a' : '#ff4d4f' }}>₽{v}</Text>,
                  },
                  {
                    title: '调整', dataIndex: 'change_percent', key: 'change_percent', width: 80,
                    render: (v, r) => <Tag color={r.action === 'increase' ? 'green' : 'red'}>{r.action === 'increase' ? '+' : '-'}{v}%</Tag>,
                  },
                  { title: '实际ROAS', dataIndex: 'actual_roas', key: 'actual_roas', width: 90 },
                  { title: '7日花费', dataIndex: 'spend_7d', key: 'spend_7d', width: 90, render: v => `₽${v}` },
                  { title: '7日收入', dataIndex: 'revenue_7d', key: 'revenue_7d', width: 90, render: v => `₽${v}` },
                ]}
              />
            )}
          </>
        )}
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
