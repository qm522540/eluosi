import { useState, useEffect, useCallback } from 'react'
import {
  Typography, Card, Table, Button, Tag, Space, Select, Row, Col,
  Statistic, Modal, Form, Input, InputNumber, message, DatePicker, Tooltip, Badge, Empty,
  Popconfirm, Tabs, Alert, Drawer, Descriptions, List, Divider, Slider, Switch, Progress,
} from 'antd'
import {
  SearchOutlined, EditOutlined, EyeOutlined, SyncOutlined, PlusOutlined,
  FundOutlined, DollarOutlined, AimOutlined, RiseOutlined, DeleteOutlined,
  DownloadOutlined, BellOutlined, ThunderboltOutlined, SettingOutlined,
  BarChartOutlined, RobotOutlined, WalletOutlined, PlayCircleOutlined,
  PauseCircleOutlined, ArrowUpOutlined, ArrowDownOutlined, MinusOutlined,
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
  getPlatformComparison, getCampaignRanking, getProductRoi,
  getAutomationRules, createAutomationRule, updateAutomationRule, deleteAutomationRule, executeRules,
  getBudgetOverview, getBudgetSuggestions,
} from '@/api/ads'
import { getShops } from '@/api/shops'
import { PLATFORMS, AD_STATUS, AD_TYPES } from '@/utils/constants'

const { Title, Text } = Typography
const { RangePicker } = DatePicker
const { TextArea } = Input

const MATCH_TYPES = {
  exact: '精确匹配',
  phrase: '短语匹配',
  broad: '广泛匹配',
}

const RULE_TYPES = {
  pause_low_roi: { label: '低ROI自动暂停', color: 'red' },
  auto_bid: { label: '自动调价', color: 'blue' },
  budget_cap: { label: '预算封顶', color: 'orange' },
  schedule: { label: '定时投放', color: 'green' },
}

const Ads = () => {
  const [searched, setSearched] = useState(false)
  const [mainTab, setMainTab] = useState('overview')

  // 汇总数据
  const [summary, setSummary] = useState(null)
  const [summaryLoading, setSummaryLoading] = useState(false)

  // 活动列表
  const [campaigns, setCampaigns] = useState([])
  const [listLoading, setListLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [filterPlatform, setFilterPlatform] = useState(null)
  const [filterStatus, setFilterStatus] = useState(null)
  const [filterShopId, setFilterShopId] = useState(null)

  // 店铺列表
  const [shops, setShops] = useState([])

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

  // 分析数据
  const [platformData, setPlatformData] = useState([])
  const [rankingData, setRankingData] = useState([])
  const [productRoiData, setProductRoiData] = useState([])
  const [analysisLoading, setAnalysisLoading] = useState(false)
  const [rankSort, setRankSort] = useState('spend')

  // 自动化规则
  const [rules, setRules] = useState([])
  const [rulesLoading, setRulesLoading] = useState(false)
  const [ruleFormVisible, setRuleFormVisible] = useState(false)
  const [editingRule, setEditingRule] = useState(null)
  const [ruleForm] = Form.useForm()
  const [ruleSubmitting, setRuleSubmitting] = useState(false)
  const [executing, setExecuting] = useState(false)

  // 预算数据
  const [budgetData, setBudgetData] = useState(null)
  const [budgetLoading, setBudgetLoading] = useState(false)
  const [suggestions, setSuggestions] = useState([])
  const [suggestionsLoading, setSuggestionsLoading] = useState(false)

  // 加载店铺列表
  useEffect(() => {
    getShops({ page: 1, page_size: 100 }).then(res => {
      setShops(res.data.items || [])
    }).catch(() => {})
  }, [])

  const canSearch = filterPlatform && filterShopId

  // ==================== 数据加载 ====================

  const fetchSummary = useCallback(async () => {
    setSummaryLoading(true)
    try {
      const params = {}
      if (filterShopId) params.shop_id = filterShopId
      if (filterPlatform) params.platform = filterPlatform
      const res = await getAdSummary(params)
      setSummary(res.data)
    } catch {
      setSummary(null)
    } finally {
      setSummaryLoading(false)
    }
  }, [filterShopId, filterPlatform])

  const fetchCampaigns = useCallback(async (p = page) => {
    setListLoading(true)
    try {
      const params = { page: p, page_size: 20 }
      if (filterPlatform) params.platform = filterPlatform
      if (filterStatus) params.status = filterStatus
      if (filterShopId) params.shop_id = filterShopId
      const res = await getCampaigns(params)
      setCampaigns(res.data.items)
      setTotal(res.data.total)
    } catch {
      message.error('获取广告活动列表失败')
    } finally {
      setListLoading(false)
    }
  }, [page, filterPlatform, filterStatus, filterShopId])

  const fetchStats = useCallback(async () => {
    if (!dateRange || dateRange.length !== 2) return
    setStatsLoading(true)
    try {
      const params = {
        start_date: dateRange[0].format('YYYY-MM-DD'),
        end_date: dateRange[1].format('YYYY-MM-DD'),
      }
      if (filterShopId) params.shop_id = filterShopId
      if (filterPlatform) params.platform = filterPlatform
      const res = await getAdStats(params)
      setStatsData(res.data || [])
    } catch {
      setStatsData([])
    } finally {
      setStatsLoading(false)
    }
  }, [dateRange, filterShopId, filterPlatform])

  const handleSearch = () => {
    setSearched(true)
    setPage(1)
    fetchCampaigns(1)
    fetchSummary()
    fetchStats()
  }

  useEffect(() => {
    if (searched) fetchStats()
  }, [dateRange])

  // ==================== 分析数据加载 ====================

  const fetchAnalysis = useCallback(async () => {
    if (!dateRange || dateRange.length !== 2) return
    setAnalysisLoading(true)
    const params = {
      start_date: dateRange[0].format('YYYY-MM-DD'),
      end_date: dateRange[1].format('YYYY-MM-DD'),
    }
    if (filterShopId) params.shop_id = filterShopId
    try {
      const [pRes, rRes, prRes] = await Promise.all([
        getPlatformComparison(params),
        getCampaignRanking({ ...params, sort_by: rankSort, limit: 10, platform: filterPlatform }),
        getProductRoi({ ...params, platform: filterPlatform }),
      ])
      setPlatformData(pRes.data || [])
      setRankingData(rRes.data || [])
      setProductRoiData(prRes.data || [])
    } catch {
      message.error('加载分析数据失败')
    } finally {
      setAnalysisLoading(false)
    }
  }, [dateRange, filterShopId, filterPlatform, rankSort])

  useEffect(() => {
    if (searched && mainTab === 'analysis') fetchAnalysis()
  }, [mainTab, dateRange, rankSort])

  // ==================== 自动化规则 ====================

  const fetchRules = async () => {
    setRulesLoading(true)
    try {
      const res = await getAutomationRules()
      setRules(res.data || [])
    } catch {
      setRules([])
    } finally {
      setRulesLoading(false)
    }
  }

  useEffect(() => {
    if (searched && mainTab === 'rules') fetchRules()
  }, [mainTab])

  const handleCreateRule = () => {
    setEditingRule(null)
    ruleForm.resetFields()
    setRuleFormVisible(true)
  }

  const handleEditRule = (record) => {
    setEditingRule(record)
    ruleForm.setFieldsValue({
      ...record,
      min_roas: record.conditions?.min_roas,
      min_spend: record.conditions?.min_spend,
      target_roas: record.conditions?.target_roas,
      max_change_pct: record.conditions?.max_change_pct,
      max_daily_spend: record.conditions?.max_daily_spend,
    })
    setRuleFormVisible(true)
  }

  const handleRuleSubmit = async () => {
    try {
      const values = await ruleForm.validateFields()
      setRuleSubmitting(true)
      const conditions = {}
      const actions = {}
      if (values.rule_type === 'pause_low_roi') {
        conditions.min_roas = values.min_roas || 1.0
        conditions.min_spend = values.min_spend || 100
        actions.action = 'pause'
      } else if (values.rule_type === 'auto_bid') {
        conditions.target_roas = values.target_roas || 2.0
        conditions.max_change_pct = values.max_change_pct || 20
        actions.action = 'adjust_bid'
      } else if (values.rule_type === 'budget_cap') {
        conditions.max_daily_spend = values.max_daily_spend || 5000
        actions.action = 'pause'
      }
      const payload = {
        name: values.name,
        rule_type: values.rule_type,
        conditions,
        actions,
        platform: values.platform || null,
        campaign_id: values.campaign_id || null,
        shop_id: values.shop_id || null,
        enabled: values.enabled ? 1 : 0,
      }
      if (editingRule) {
        await updateAutomationRule(editingRule.id, payload)
        message.success('规则更新成功')
      } else {
        await createAutomationRule(payload)
        message.success('规则创建成功')
      }
      setRuleFormVisible(false)
      fetchRules()
    } catch (err) {
      if (err.errorFields) return
      message.error(err.message || '操作失败')
    } finally {
      setRuleSubmitting(false)
    }
  }

  const handleDeleteRule = async (id) => {
    try {
      await deleteAutomationRule(id)
      message.success('规则已删除')
      fetchRules()
    } catch (err) {
      message.error(err.message || '删除失败')
    }
  }

  const handleToggleRule = async (record) => {
    try {
      await updateAutomationRule(record.id, { enabled: record.enabled ? 0 : 1 })
      message.success(record.enabled ? '规则已禁用' : '规则已启用')
      fetchRules()
    } catch (err) {
      message.error(err.message || '操作失败')
    }
  }

  const handleExecuteRules = async () => {
    setExecuting(true)
    try {
      const res = await executeRules()
      message.success(`规则执行完成，检查了 ${res.data?.rules_checked || 0} 条规则`)
      fetchRules()
      if (searched) fetchCampaigns()
    } catch (err) {
      message.error(err.message || '执行失败')
    } finally {
      setExecuting(false)
    }
  }

  // ==================== 预算管理 ====================

  const fetchBudget = async () => {
    setBudgetLoading(true)
    try {
      const params = {}
      if (filterShopId) params.shop_id = filterShopId
      if (filterPlatform) params.platform = filterPlatform
      const res = await getBudgetOverview(params)
      setBudgetData(res.data)
    } catch {
      setBudgetData(null)
    } finally {
      setBudgetLoading(false)
    }
  }

  const fetchBudgetSuggestions = async () => {
    setSuggestionsLoading(true)
    try {
      const params = {}
      if (filterShopId) params.shop_id = filterShopId
      if (filterPlatform) params.platform = filterPlatform
      const res = await getBudgetSuggestions(params)
      setSuggestions(res.data || [])
    } catch {
      setSuggestions([])
    } finally {
      setSuggestionsLoading(false)
    }
  }

  useEffect(() => {
    if (searched && mainTab === 'budget') {
      fetchBudget()
      fetchBudgetSuggestions()
    }
  }, [mainTab])

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
    if (filterPlatform) createForm.setFieldValue('platform', filterPlatform)
    if (filterShopId) createForm.setFieldValue('shop_id', filterShopId)
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
    try {
      const res = await getCampaign(id)
      setDetailData(res.data)
      fetchAdGroups(id)
    } catch {
      message.error('获取广告详情失败')
    } finally {
      setDetailLoading(false)
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
      if (filterShopId) params.shop_id = filterShopId
      if (filterPlatform) params.platform = filterPlatform
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
      ellipsis: true,
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
      title: '日预算',
      dataIndex: 'daily_budget',
      key: 'daily_budget',
      width: 110,
      align: 'right',
      render: (v) => v != null ? `₽${v.toLocaleString()}` : '-',
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
      title: '开始日期',
      dataIndex: 'start_date',
      key: 'start_date',
      width: 110,
      render: (v) => v || '-',
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

  // 平台对比图
  const getPlatformChartOption = () => {
    const labels = { wb: 'Wildberries', ozon: 'Ozon', yandex: 'Yandex' }
    const platforms = platformData.map(p => labels[p.platform] || p.platform)
    return {
      tooltip: { trigger: 'axis' },
      legend: { data: ['花费', '收入', 'ROAS'] },
      grid: { left: 60, right: 60, top: 40, bottom: 30 },
      xAxis: { type: 'category', data: platforms },
      yAxis: [
        { type: 'value', name: '金额 (₽)' },
        { type: 'value', name: 'ROAS', position: 'right' },
      ],
      series: [
        { name: '花费', type: 'bar', data: platformData.map(p => p.spend), itemStyle: { color: '#ff7875' }, barMaxWidth: 40 },
        { name: '收入', type: 'bar', data: platformData.map(p => p.revenue), itemStyle: { color: '#95de64' }, barMaxWidth: 40 },
        { name: 'ROAS', type: 'line', yAxisIndex: 1, data: platformData.map(p => p.roas), itemStyle: { color: '#faad14' } },
      ],
    }
  }

  // ==================== 广告组表格列 ====================

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

  // ==================== 关键词表格列 ====================

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

  return (
    <div>
      {/* 顶部操作栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0 }}>广告管理</Title>
        <Space>
          <Select
            placeholder="选择平台"
            allowClear
            style={{ width: 150 }}
            value={filterPlatform}
            onChange={(v) => { setFilterPlatform(v); setFilterShopId(null) }}
            options={[
              { value: 'wb', label: 'Wildberries' },
              { value: 'ozon', label: 'Ozon' },
              { value: 'yandex', label: 'Yandex Market' },
            ]}
          />
          <Select
            placeholder="选择店铺"
            allowClear
            style={{ width: 160 }}
            value={filterShopId}
            onChange={setFilterShopId}
            disabled={!filterPlatform}
            options={shops.filter(s => s.platform === filterPlatform).map(s => ({ value: s.id, label: s.name }))}
          />
          <Select
            style={{ width: 120 }}
            value={filterStatus}
            onChange={setFilterStatus}
            options={[
              { value: null, label: '全部状态' },
              ...Object.entries(AD_STATUS).map(([k, v]) => ({ value: k, label: v.label })),
            ]}
          />
          <Button type="primary" icon={<SearchOutlined />} disabled={!canSearch} onClick={handleSearch}>确定</Button>
          <Button icon={<PlusOutlined />} onClick={handleCreateCampaign}>新建活动</Button>
          <Button icon={<SyncOutlined spin={syncing} />} loading={syncing} onClick={handleSync}>同步</Button>
          <Button icon={<BellOutlined />} onClick={handleShowAlerts}>告警</Button>
          <Button icon={<SettingOutlined />} onClick={handleShowConfig}>配置</Button>
        </Space>
      </div>

      {!searched ? (
        <Card>
          <Empty description="请选择平台和店铺后点击确定查询广告数据" />
        </Card>
      ) : (
        <>
          {/* 汇总卡片 */}
          <Row gutter={16} style={{ marginBottom: 24 }}>
            <Col span={6}>
              <Card size="small" loading={summaryLoading}>
                <Statistic title="总展示" value={summary?.total_impressions || 0} prefix={<FundOutlined />} valueStyle={{ color: '#597ef7' }} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small" loading={summaryLoading}>
                <Statistic title="总点击" value={summary?.total_clicks || 0} prefix={<AimOutlined />}
                  suffix={summary?.avg_ctr != null ? <span style={{ fontSize: 14, color: '#999' }}>CTR {summary.avg_ctr}%</span> : null} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small" loading={summaryLoading}>
                <Statistic title="总花费" value={summary?.total_spend || 0} prefix={<DollarOutlined />} precision={2} suffix="₽" valueStyle={{ color: '#ff7875' }} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small" loading={summaryLoading}>
                <Statistic title="ROAS" value={summary?.overall_roas || 0} prefix={<RiseOutlined />} precision={2} suffix="x"
                  valueStyle={{ color: summary?.overall_roas >= 1 ? '#52c41a' : '#ff4d4f' }} />
              </Card>
            </Col>
          </Row>

          {/* 主功能Tab */}
          <Tabs activeKey={mainTab} onChange={setMainTab} items={[
            {
              key: 'overview',
              label: <span><FundOutlined /> 概览</span>,
              children: (
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

                  {/* 趋势图表 */}
                  <Card title="广告趋势" size="small"
                    extra={
                      <Space>
                        <Button icon={<DownloadOutlined />} size="small" loading={exporting} onClick={handleExport}>导出CSV</Button>
                        <RangePicker value={dateRange} onChange={setDateRange} allowClear={false}
                          presets={[
                            { label: '近7天', value: [dayjs().subtract(6, 'day'), dayjs()] },
                            { label: '近30天', value: [dayjs().subtract(29, 'day'), dayjs()] },
                          ]}
                        />
                      </Space>
                    }
                  >
                    <ReactECharts option={getChartOption()} style={{ height: 300 }} showLoading={statsLoading} />
                  </Card>
                </>
              ),
            },
            {
              key: 'analysis',
              label: <span><BarChartOutlined /> 数据分析</span>,
              children: (
                <>
                  <Row gutter={16} style={{ marginBottom: 16 }}>
                    <Col span={24}>
                      <RangePicker value={dateRange} onChange={setDateRange} allowClear={false}
                        presets={[
                          { label: '近7天', value: [dayjs().subtract(6, 'day'), dayjs()] },
                          { label: '近30天', value: [dayjs().subtract(29, 'day'), dayjs()] },
                          { label: '近90天', value: [dayjs().subtract(89, 'day'), dayjs()] },
                        ]}
                      />
                    </Col>
                  </Row>

                  {/* 平台对比 */}
                  <Card title="平台对比分析" size="small" style={{ marginBottom: 24 }} loading={analysisLoading}>
                    {platformData.length > 0 ? (
                      <>
                        <ReactECharts option={getPlatformChartOption()} style={{ height: 280 }} />
                        <Table size="small" dataSource={platformData} rowKey="platform" pagination={false} style={{ marginTop: 16 }}
                          columns={[
                            { title: '平台', dataIndex: 'platform', render: p => <Tag color={PLATFORMS[p]?.color}>{PLATFORMS[p]?.label || p}</Tag> },
                            { title: '展示', dataIndex: 'impressions', render: v => v.toLocaleString() },
                            { title: '点击', dataIndex: 'clicks', render: v => v.toLocaleString() },
                            { title: 'CTR%', dataIndex: 'ctr', render: v => `${v}%` },
                            { title: '花费', dataIndex: 'spend', render: v => `₽${v.toLocaleString()}` },
                            { title: '收入', dataIndex: 'revenue', render: v => `₽${v.toLocaleString()}` },
                            { title: 'ROAS', dataIndex: 'roas', render: v => <Text style={{ color: v >= 1 ? '#52c41a' : '#ff4d4f' }}>{v}x</Text> },
                            { title: '转化率', dataIndex: 'conversion_rate', render: v => `${v}%` },
                          ]}
                        />
                      </>
                    ) : <Empty description="暂无多平台数据" />}
                  </Card>

                  {/* 活动排名 */}
                  <Card title="活动TOP排名" size="small" style={{ marginBottom: 24 }}
                    extra={
                      <Select value={rankSort} onChange={setRankSort} size="small" style={{ width: 120 }}
                        options={[
                          { value: 'spend', label: '按花费排序' },
                          { value: 'revenue', label: '按收入排序' },
                          { value: 'clicks', label: '按点击排序' },
                          { value: 'orders', label: '按订单排序' },
                        ]}
                      />
                    }
                  >
                    <Table size="small" dataSource={rankingData} rowKey="campaign_id" pagination={false} loading={analysisLoading}
                      columns={[
                        { title: '排名', key: 'rank', width: 60, render: (_, __, i) => <Text strong>{i + 1}</Text> },
                        { title: '活动名称', dataIndex: 'name', ellipsis: true },
                        { title: '平台', dataIndex: 'platform', width: 110, render: p => <Tag color={PLATFORMS[p]?.color}>{PLATFORMS[p]?.label}</Tag> },
                        { title: '花费', dataIndex: 'spend', width: 100, render: v => `₽${v.toLocaleString()}` },
                        { title: '收入', dataIndex: 'revenue', width: 100, render: v => `₽${v.toLocaleString()}` },
                        { title: '点击', dataIndex: 'clicks', width: 80 },
                        { title: '订单', dataIndex: 'orders', width: 70 },
                        { title: 'ROAS', dataIndex: 'roas', width: 80, render: v => <Text style={{ color: v >= 1 ? '#52c41a' : '#ff4d4f' }}>{v}x</Text> },
                        { title: 'ACOS%', dataIndex: 'acos', width: 80, render: v => `${v}%` },
                      ]}
                    />
                  </Card>

                  {/* 商品ROI */}
                  <Card title="商品级ROI分析" size="small">
                    <Table size="small" dataSource={productRoiData} rowKey={(_, i) => i} loading={analysisLoading}
                      pagination={{ pageSize: 10, size: 'small' }}
                      columns={[
                        { title: '商品/广告组', dataIndex: 'group_name', ellipsis: true },
                        { title: '商品ID', dataIndex: 'listing_id', width: 100, render: v => v || '-' },
                        { title: '平台', dataIndex: 'platform', width: 100, render: p => <Tag color={PLATFORMS[p]?.color}>{PLATFORMS[p]?.label}</Tag> },
                        { title: '花费', dataIndex: 'spend', width: 100, render: v => `₽${v}` },
                        { title: '收入', dataIndex: 'revenue', width: 100, render: v => `₽${v}` },
                        { title: 'ROAS', dataIndex: 'roas', width: 80, render: v => <Text style={{ color: v >= 1 ? '#52c41a' : '#ff4d4f' }}>{v}x</Text> },
                        { title: 'CPA', dataIndex: 'cpa', width: 80, render: v => v ? `₽${v}` : '-' },
                        { title: '订单', dataIndex: 'orders', width: 70 },
                      ]}
                    />
                  </Card>
                </>
              ),
            },
            {
              key: 'rules',
              label: <span><RobotOutlined /> 自动化规则</span>,
              children: (
                <>
                  <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
                    <Text>配置自动化规则，系统将每小时自动检查并执行。</Text>
                    <Space>
                      <Button icon={<PlayCircleOutlined />} loading={executing} onClick={handleExecuteRules}>立即执行</Button>
                      <Button type="primary" icon={<PlusOutlined />} onClick={handleCreateRule}>新建规则</Button>
                    </Space>
                  </div>

                  <Table size="small" dataSource={rules} rowKey="id" loading={rulesLoading} pagination={false}
                    columns={[
                      { title: '规则名称', dataIndex: 'name', ellipsis: true },
                      {
                        title: '类型', dataIndex: 'rule_type', width: 140,
                        render: v => <Tag color={RULE_TYPES[v]?.color}>{RULE_TYPES[v]?.label || v}</Tag>,
                      },
                      {
                        title: '作用范围', key: 'scope', width: 160,
                        render: (_, r) => {
                          const parts = []
                          if (r.platform) parts.push(PLATFORMS[r.platform]?.label || r.platform)
                          if (r.campaign_id) parts.push(`活动#${r.campaign_id}`)
                          if (r.shop_id) parts.push(`店铺#${r.shop_id}`)
                          return parts.length ? parts.join(' / ') : '全部'
                        },
                      },
                      {
                        title: '条件', key: 'conditions', ellipsis: true,
                        render: (_, r) => {
                          const c = r.conditions || {}
                          if (r.rule_type === 'pause_low_roi') return `ROAS < ${c.min_roas || 1}，花费 >= ₽${c.min_spend || 100}`
                          if (r.rule_type === 'auto_bid') return `目标ROAS ${c.target_roas || 2}，最大调幅 ${c.max_change_pct || 20}%`
                          if (r.rule_type === 'budget_cap') return `日花费上限 ₽${c.max_daily_spend || 0}`
                          if (r.rule_type === 'schedule') return `投放时段: ${(c.active_hours || []).join(',')}时`
                          return '-'
                        },
                      },
                      {
                        title: '状态', dataIndex: 'enabled', width: 80,
                        render: (v, r) => <Switch size="small" checked={!!v} onChange={() => handleToggleRule(r)} />,
                      },
                      {
                        title: '触发次数', dataIndex: 'trigger_count', width: 80, align: 'center',
                      },
                      {
                        title: '最后触发', dataIndex: 'last_triggered_at', width: 160,
                        render: v => v ? dayjs(v).format('MM-DD HH:mm') : '-',
                      },
                      {
                        title: '操作', key: 'action', width: 120,
                        render: (_, record) => (
                          <Space size="small">
                            <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEditRule(record)} />
                            <Popconfirm title="确定删除此规则？" onConfirm={() => handleDeleteRule(record.id)}>
                              <Button type="link" size="small" danger icon={<DeleteOutlined />} />
                            </Popconfirm>
                          </Space>
                        ),
                      },
                    ]}
                  />
                </>
              ),
            },
            {
              key: 'budget',
              label: <span><WalletOutlined /> 预算管理</span>,
              children: (
                <>
                  {/* 预算汇总 */}
                  {budgetData?.summary && (
                    <Row gutter={16} style={{ marginBottom: 24 }}>
                      <Col span={5}>
                        <Card size="small" loading={budgetLoading}>
                          <Statistic title="总日预算" value={budgetData.summary.total_daily_budget} prefix="₽" precision={0} />
                        </Card>
                      </Col>
                      <Col span={5}>
                        <Card size="small" loading={budgetLoading}>
                          <Statistic title="今日花费" value={budgetData.summary.total_today_spend} prefix="₽" precision={2}
                            valueStyle={{ color: '#ff7875' }} />
                        </Card>
                      </Col>
                      <Col span={5}>
                        <Card size="small" loading={budgetLoading}>
                          <Statistic title="本月花费" value={budgetData.summary.total_month_spend} prefix="₽" precision={2} />
                        </Card>
                      </Col>
                      <Col span={5}>
                        <Card size="small" loading={budgetLoading}>
                          <Statistic title="预算使用率" value={budgetData.summary.budget_usage_pct} suffix="%"
                            valueStyle={{ color: budgetData.summary.budget_usage_pct >= 80 ? '#ff4d4f' : '#52c41a' }} />
                        </Card>
                      </Col>
                      <Col span={4}>
                        <Card size="small" loading={budgetLoading}>
                          <Statistic title="活跃活动" value={budgetData.summary.active_campaigns}
                            suffix={`/ ${budgetData.summary.total_campaigns}`} />
                        </Card>
                      </Col>
                    </Row>
                  )}

                  {/* 预算预警 */}
                  {budgetData?.alerts?.length > 0 && (
                    <Alert
                      type="warning"
                      showIcon
                      style={{ marginBottom: 16 }}
                      message={`${budgetData.alerts.length} 个活动预算使用率较高`}
                      description={
                        <ul style={{ margin: '8px 0', paddingLeft: 20 }}>
                          {budgetData.alerts.map((a, i) => (
                            <li key={i}>
                              <Tag color={a.level === 'critical' ? 'red' : 'orange'}>{a.level === 'critical' ? '超标' : '预警'}</Tag>
                              {a.name}: {a.message}（今日 ₽{a.today_spend} / 预算 ₽{a.daily_budget}）
                            </li>
                          ))}
                        </ul>
                      }
                    />
                  )}

                  {/* 活动预算明细 */}
                  <Card title="活动预算消耗明细" size="small" style={{ marginBottom: 24 }}>
                    <Table size="small" dataSource={budgetData?.campaigns || []} rowKey="campaign_id" loading={budgetLoading}
                      pagination={{ pageSize: 10, size: 'small' }}
                      columns={[
                        { title: '活动名称', dataIndex: 'name', ellipsis: true },
                        { title: '平台', dataIndex: 'platform', width: 100, render: p => <Tag color={PLATFORMS[p]?.color}>{PLATFORMS[p]?.label}</Tag> },
                        { title: '日预算', dataIndex: 'daily_budget', width: 100, render: v => v ? `₽${v}` : '不限' },
                        { title: '今日花费', dataIndex: 'today_spend', width: 100, render: v => `₽${v}` },
                        {
                          title: '使用率', dataIndex: 'budget_usage_pct', width: 140,
                          render: v => v > 0 ? (
                            <Progress percent={Math.min(v, 100)} size="small"
                              strokeColor={v >= 100 ? '#ff4d4f' : v >= 80 ? '#faad14' : '#52c41a'}
                              format={() => `${v}%`}
                            />
                          ) : '-',
                        },
                        { title: '均日消耗', dataIndex: 'avg_daily_spend', width: 100, render: v => `₽${v}` },
                        { title: '本月花费', dataIndex: 'month_spend', width: 100, render: v => `₽${v}` },
                        {
                          title: '剩余天数', dataIndex: 'days_remaining', width: 90,
                          render: v => v != null ? (
                            <Text style={{ color: v <= 3 ? '#ff4d4f' : v <= 7 ? '#faad14' : '#52c41a' }}>{v}天</Text>
                          ) : '-',
                        },
                        {
                          title: '状态', dataIndex: 'status', width: 80,
                          render: s => <Badge color={AD_STATUS[s]?.color} text={AD_STATUS[s]?.label || s} />,
                        },
                      ]}
                    />
                  </Card>

                  {/* 预算优化建议 */}
                  <Card title="预算分配优化建议" size="small" loading={suggestionsLoading}>
                    {suggestions.length > 0 ? (
                      <Table size="small" dataSource={suggestions} rowKey="campaign_id" pagination={false}
                        columns={[
                          { title: '活动名称', dataIndex: 'name', ellipsis: true },
                          { title: '平台', dataIndex: 'platform', width: 100, render: p => <Tag color={PLATFORMS[p]?.color}>{PLATFORMS[p]?.label}</Tag> },
                          { title: '当前预算', dataIndex: 'current_daily_budget', width: 100, render: v => v ? `₽${v}` : '不限' },
                          {
                            title: '建议预算', dataIndex: 'suggested_budget', width: 100,
                            render: (v, r) => (
                              <Text style={{ color: r.action === 'increase' ? '#52c41a' : r.action === 'decrease' ? '#ff4d4f' : '#999' }}>
                                ₽{v}
                              </Text>
                            ),
                          },
                          {
                            title: '建议', dataIndex: 'action', width: 80,
                            render: v => v === 'increase'
                              ? <Tag color="green" icon={<ArrowUpOutlined />}>加预算</Tag>
                              : v === 'decrease'
                                ? <Tag color="red" icon={<ArrowDownOutlined />}>降预算</Tag>
                                : <Tag icon={<MinusOutlined />}>维持</Tag>,
                          },
                          { title: '7日ROAS', dataIndex: 'roas_7d', width: 90, render: v => <Text style={{ color: v >= 1 ? '#52c41a' : '#ff4d4f' }}>{v}x</Text> },
                          { title: '原因', dataIndex: 'reason', ellipsis: true },
                        ]}
                      />
                    ) : <Empty description="暂无预算优化建议" />}
                  </Card>
                </>
              ),
            },
          ]} />
        </>
      )}

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

      {/* ==================== 详情抽屉（含广告组/关键词管理）==================== */}
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
                <Descriptions column={2} bordered size="small">
                  <Descriptions.Item label="名称">{detailData.name}</Descriptions.Item>
                  <Descriptions.Item label="平台">
                    <Tag color={PLATFORMS[detailData.platform]?.color}>{PLATFORMS[detailData.platform]?.label}</Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="广告类型">{AD_TYPES[detailData.ad_type]?.label || detailData.ad_type}</Descriptions.Item>
                  <Descriptions.Item label="状态">
                    <Badge color={AD_STATUS[detailData.status]?.color} text={AD_STATUS[detailData.status]?.label || detailData.status} />
                  </Descriptions.Item>
                  <Descriptions.Item label="日预算">{detailData.daily_budget != null ? `₽${detailData.daily_budget}` : '不限'}</Descriptions.Item>
                  <Descriptions.Item label="总预算">{detailData.total_budget != null ? `₽${detailData.total_budget}` : '不限'}</Descriptions.Item>
                  <Descriptions.Item label="开始日期">{detailData.start_date || '-'}</Descriptions.Item>
                  <Descriptions.Item label="结束日期">{detailData.end_date || '-'}</Descriptions.Item>
                  <Descriptions.Item label="平台活动ID" span={2}>{detailData.platform_campaign_id || '-'}</Descriptions.Item>
                </Descriptions>
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

      {/* ==================== 自动化规则 表单弹窗 ==================== */}
      <Modal
        title={editingRule ? '编辑自动化规则' : '新建自动化规则'}
        open={ruleFormVisible}
        onOk={handleRuleSubmit}
        onCancel={() => setRuleFormVisible(false)}
        confirmLoading={ruleSubmitting}
        destroyOnClose
        width={600}
      >
        <Form form={ruleForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="name" label="规则名称" rules={[{ required: true, message: '请输入规则名称' }]}>
            <Input maxLength={200} placeholder="例如：低ROI自动暂停" />
          </Form.Item>
          <Form.Item name="rule_type" label="规则类型" rules={[{ required: true, message: '请选择规则类型' }]}>
            <Select options={Object.entries(RULE_TYPES).map(([k, v]) => ({ value: k, label: v.label }))} />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="platform" label="限定平台（可选）">
                <Select allowClear placeholder="全部平台" options={[
                  { value: 'wb', label: 'Wildberries' },
                  { value: 'ozon', label: 'Ozon' },
                  { value: 'yandex', label: 'Yandex' },
                ]} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="enabled" label="启用" valuePropName="checked" initialValue={true}>
                <Switch />
              </Form.Item>
            </Col>
          </Row>

          <Divider style={{ margin: '8px 0 16px' }}>规则条件</Divider>

          <Form.Item noStyle shouldUpdate={(prev, cur) => prev.rule_type !== cur.rule_type}>
            {({ getFieldValue }) => {
              const rt = getFieldValue('rule_type')
              if (rt === 'pause_low_roi') return (
                <Row gutter={16}>
                  <Col span={12}>
                    <Form.Item name="min_roas" label="最低ROAS阈值" initialValue={1.0}>
                      <InputNumber min={0} step={0.1} style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item name="min_spend" label="最低花费(₽)才触发" initialValue={100}>
                      <InputNumber min={0} step={50} style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                </Row>
              )
              if (rt === 'auto_bid') return (
                <Row gutter={16}>
                  <Col span={12}>
                    <Form.Item name="target_roas" label="目标ROAS" initialValue={2.0}>
                      <InputNumber min={0.1} step={0.1} style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item name="max_change_pct" label="最大调整幅度(%)" initialValue={20}>
                      <InputNumber min={1} max={50} style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                </Row>
              )
              if (rt === 'budget_cap') return (
                <Form.Item name="max_daily_spend" label="日花费上限(₽)" initialValue={5000}>
                  <InputNumber min={100} step={500} style={{ width: '100%' }} />
                </Form.Item>
              )
              if (rt === 'schedule') return (
                <Form.Item name="active_hours" label="投放时段（选择小时）">
                  <Select mode="multiple" placeholder="选择活跃小时"
                    options={Array.from({ length: 24 }, (_, i) => ({ value: i, label: `${i}:00` }))}
                  />
                </Form.Item>
              )
              return <Text type="secondary">请先选择规则类型</Text>
            }}
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default Ads
