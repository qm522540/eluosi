import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Typography, Card, Table, Button, Tag, Space, Row, Col,
  Modal, Form, Input, InputNumber, message, Tooltip, Empty, Switch, Collapse, DatePicker, Avatar, Badge, Alert, Spin,
} from 'antd'
import {
  EditOutlined, CheckOutlined, CloseOutlined, RobotOutlined,
  ArrowUpOutlined, ArrowDownOutlined, HistoryOutlined, SettingOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { formatMoscowTime, formatMoscowShort } from '@/utils/time'
import {
  getAIPricingConfigs, updateAIPricingConfig,
  triggerAIAnalysis, getAIPricingSuggestions,
  approveAIPricingSuggestion, rejectAIPricingSuggestion,
  ignoreAIPricingSuggestion, restoreAIPricingSuggestion,
  toggleAIAutoExecute, getAIPricingHistory,
} from '@/api/ads'
import { triggerWBAnalysis, getWBSuggestions, rejectWBSuggestion } from '@/api/wb_pricing'
import { getPromoStatus, getPromoCalendars, createPromoCalendar } from '@/api/ai_pricing'
import { getDataStatus, syncData, downloadData } from '@/api/bid_management'
import { useAuthStore } from '@/stores/authStore'
import WbProductImg from '@/components/WbProductImg'

const { Text } = Typography
const { RangePicker } = DatePicker

// ==================== 平台配置 ====================

const PLATFORM_CONFIG = {
  ozon: {
    label: 'Ozon',
    color: '#005BFF',
    mode: 'full',
    description: '商品级别出价·支持自动执行',
  },
  wb: {
    label: 'Wildberries',
    color: '#CB11AB',
    mode: 'full',
    description: '商品级别CPM出价·支持自动执行',
  },
  yandex: {
    label: 'Yandex Market',
    color: '#FFCC00',
    mode: 'coming',
    description: '即将上线',
  },
}

const templateTypeConfig = {
  default: { color: 'blue', label: '标准' },
  conservative: { color: 'green', label: '保守' },
  aggressive: { color: 'red', label: '激进' },
  custom: { color: 'purple', label: '自定义' },
}

// ==================== 商品阶段配置 ====================

const STAGE_CONFIG = {
  cold_start: { color: 'blue', label: '冷启动', tip: '新品期，以曝光为主，不因ROAS低降价' },
  testing: { color: 'orange', label: '测试期', tip: 'CTR ok但CR偏低，降价减耗等转化改善' },
  growing: { color: 'green', label: '放量期', tip: 'CTR和CR均达标，ROAS驱动加大投入' },
  declining: { color: 'red', label: '衰退预警', tip: 'ROAS持续下滑，收缩预算控制亏损' },
  unknown: { color: 'default', label: '数据不足', tip: '历史数据不足，保守处理' },
}

const OPTIMIZE_LABEL = {
  impression: '曝光量', ctr_cr: 'CTR/CR', roas: 'ROAS', profit: '利润', auto: '综合',
}

const PROMO_PHASE_MAP = {
  pre_heat: { color: 'gold', label: '预热' },
  peak: { color: 'red', label: '冲刺' },
  recovery: { color: 'cyan', label: '恢复' },
}

// 商品阶段列（共享）
const stageColumn = {
  title: '商品阶段', dataIndex: 'product_stage', width: 110,
  render: (stage) => {
    const cfg = STAGE_CONFIG[stage] || STAGE_CONFIG.unknown
    return <Tooltip title={cfg.tip}><Tag color={cfg.color} style={{ cursor: 'help' }}>{cfg.label}</Tag></Tooltip>
  },
}

const optimizeColumn = {
  title: '优化目标', dataIndex: 'stage_optimize_target', width: 90,
  render: target => <span style={{ fontSize: 12, color: '#999' }}>{OPTIMIZE_LABEL[target] || target || '-'}</span>,
}

const promoColumn = {
  title: '大促', dataIndex: 'promo_phase', width: 80,
  render: (phase, record) => {
    if (!phase) return '-'
    const cfg = PROMO_PHASE_MAP[phase] || {}
    return (
      <Tooltip title={`出价系数×${record.promo_multiplier || '?'}`}>
        <Tag color={cfg.color}>{cfg.label}</Tag>
      </Tooltip>
    )
  },
}

// ==================== 大促状态提示条 ====================

const PromoStatusBar = ({ tenantId }) => {
  const [promoStatus, setPromoStatus] = useState(null)

  useEffect(() => {
    if (!tenantId) return
    getPromoStatus(tenantId).then(res => {
      if (res.data?.is_promo_period) setPromoStatus(res.data)
    }).catch(() => {})
  }, [tenantId])

  if (!promoStatus) return null

  const phaseConfig = {
    pre_heat: { type: 'warning', icon: '🔥', label: '预热期' },
    peak: { type: 'error', icon: '🚀', label: '大促冲刺' },
    recovery: { type: 'info', icon: '📉', label: '恢复期' },
  }
  const cfg = phaseConfig[promoStatus.promo_phase] || {}

  return (
    <Alert
      type={cfg.type}
      showIcon={false}
      style={{ marginBottom: 16 }}
      message={
        <Space>
          <span style={{ fontSize: 16 }}>{cfg.icon}</span>
          <strong>{promoStatus.promo_name} · {cfg.label}</strong>
          <Tag color="orange">出价系数 ×{promoStatus.bid_multiplier}</Tag>
          <span style={{ fontSize: 13, color: '#999' }}>{promoStatus.strategy_hint}</span>
        </Space>
      }
    />
  )
}

// ==================== 大促日历管理 ====================

const PromoCalendarPanel = ({ tenantId }) => {
  const [calendars, setCalendars] = useState([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [form] = Form.useForm()

  const fetchCalendars = useCallback(async () => {
    if (!tenantId) return
    setLoading(true)
    try {
      const res = await getPromoCalendars(tenantId)
      setCalendars(res.data || [])
    } catch {
      setCalendars([])
    } finally {
      setLoading(false)
    }
  }, [tenantId])

  useEffect(() => {
    fetchCalendars()
  }, [fetchCalendars])

  const handleAdd = async () => {
    try {
      const values = await form.validateFields()
      setSubmitting(true)
      await createPromoCalendar({
        tenant_id: tenantId,
        ...values,
        promo_date: values.promo_date.format('YYYY-MM-DD'),
        pre_heat_days: 1,
        recovery_days: 3,
      })
      message.success('大促节点已添加')
      setModalOpen(false)
      form.resetFields()
      fetchCalendars()
    } catch (err) {
      if (err.errorFields) return
      message.error(err.message || '添加失败')
    } finally {
      setSubmitting(false)
    }
  }

  const columns = [
    { title: '大促名称', dataIndex: 'promo_name', width: 120 },
    { title: '大促日期', dataIndex: 'promo_date', width: 120 },
    { title: '预热系数', dataIndex: 'pre_heat_multiplier', width: 90, render: v => `×${v}` },
    {
      title: '冲刺系数', dataIndex: 'peak_multiplier', width: 90,
      render: v => <span style={{ color: '#ff4d4f', fontWeight: 500 }}>×{v}</span>,
    },
    {
      title: '恢复1/2/3天', width: 140,
      render: (_, r) => `×${r.recovery_day1_multiplier || '-'} / ×${r.recovery_day2_multiplier || '-'} / ×${r.recovery_day3_multiplier || '-'}`,
    },
  ]

  return (
    <>
      <Collapse style={{ marginTop: 24 }} items={[{
        key: 'promo',
        label: '📅 大促日历管理',
        extra: (
          <Button size="small" type="primary" onClick={e => { e.stopPropagation(); setModalOpen(true) }}>
            添加大促
          </Button>
        ),
        children: (
          <Table dataSource={calendars} columns={columns} rowKey="id" pagination={false} size="small" loading={loading} />
        ),
      }]} />

      <Modal
        title="添加大促节点"
        open={modalOpen}
        onOk={handleAdd}
        onCancel={() => setModalOpen(false)}
        confirmLoading={submitting}
        okText="确认添加"
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="promo_name" label="大促名称" rules={[{ required: true, message: '请输入大促名称' }]}>
            <Input placeholder="如：妇女节、黑五" />
          </Form.Item>
          <Form.Item name="promo_date" label="大促日期" rules={[{ required: true, message: '请选择日期' }]}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="pre_heat_multiplier" label="预热期出价系数" initialValue={1.3}>
                <InputNumber min={1.0} max={2.0} step={0.1} style={{ width: '100%' }} addonBefore="×" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="peak_multiplier" label="大促当天出价系数" initialValue={1.7}>
                <InputNumber min={1.0} max={3.0} step={0.1} style={{ width: '100%' }} addonBefore="×" />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </>
  )
}

// ==================== Yandex占位 ====================

const YandexComingSoon = () => (
  <div style={{ textAlign: 'center', padding: '60px 0', color: '#999' }}>
    <div style={{ fontSize: 48, marginBottom: 16 }}>🚀</div>
    <div style={{ fontSize: 18, fontWeight: 500, marginBottom: 8 }}>
      Yandex Market AI调价即将上线
    </div>
    <div style={{ fontSize: 14 }}>
      目前正在开发中，敬请期待
    </div>
  </div>
)

// ==================== WB建议模式 ====================

const WBAIPricing = ({ shopId }) => {
  const [suggestions, setSuggestions] = useState([])
  const [loading, setLoading] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)

  const fetchSuggestions = useCallback(async () => {
    if (!shopId) return
    setLoading(true)
    try {
      const res = await getWBSuggestions(shopId, { status: 'pending' })
      setSuggestions(res.data?.items || res.data || [])
    } catch {
      setSuggestions([])
    } finally {
      setLoading(false)
    }
  }, [shopId])

  useEffect(() => {
    fetchSuggestions()
  }, [fetchSuggestions])

  const handleAnalyze = async () => {
    setAnalyzing(true)
    try {
      const res = await triggerWBAnalysis(shopId)
      const data = res.data || {}
      message.success(`分析完成：分析了 ${data.analyzed_count || 0} 个活动，生成 ${data.suggestion_count || 0} 条建议`)
      fetchSuggestions()
    } catch (err) {
      message.error(err.message || '分析失败')
    } finally {
      setAnalyzing(false)
    }
  }

  const handleReject = async (id) => {
    try {
      await rejectWBSuggestion(id)
      message.success('已忽略')
      fetchSuggestions()
    } catch (err) {
      message.error(err.message || '操作失败')
    }
  }

  const columns = [
    {
      title: '广告活动', dataIndex: 'campaign_name', width: 200,
      render: (name, record) => (
        <div>
          <div style={{ fontWeight: 500 }}>{name || '-'}</div>
          <div style={{ fontSize: 12, color: '#999' }}>
            ID: {record.platform_campaign_id || record.campaign_id || '-'}
          </div>
        </div>
      ),
    },
    {
      title: '当前CPM', dataIndex: 'current_bid', width: 100, align: 'right',
      render: v => `₽${Math.round(v)}`,
    },
    {
      title: '建议CPM', dataIndex: 'suggested_bid', width: 120, align: 'right',
      render: (v, record) => {
        const isUp = record.adjust_pct > 0
        return (
          <Space>
            <span style={{ fontWeight: 600, color: isUp ? '#52c41a' : '#ff4d4f', fontSize: 15 }}>
              ₽{Math.round(v)}
            </span>
            <Tag color={isUp ? 'success' : 'error'} style={{ margin: 0 }}>
              {isUp ? '↑' : '↓'}{Math.abs(record.adjust_pct).toFixed(1)}%
            </Tag>
          </Space>
        )
      },
    },
    {
      title: '当前ROAS', dataIndex: 'current_roas', width: 100, align: 'right',
      render: v => v ? `${v}x` : '-',
    },
    {
      title: '预期ROAS', dataIndex: 'expected_roas', width: 100, align: 'right',
      render: (v, record) => {
        if (!v) return '-'
        const isUp = v > (record.current_roas || 0)
        return <span style={{ color: isUp ? '#52c41a' : '#ff4d4f' }}>{v}x {isUp ? '↑' : '↓'}</span>
      },
    },
    stageColumn,
    optimizeColumn,
    promoColumn,
    {
      title: 'AI理由', dataIndex: 'reason', ellipsis: { showTitle: false },
      render: text => <Tooltip title={text}><span style={{ cursor: 'help' }}>{text}</span></Tooltip>,
    },
    {
      title: '数据', dataIndex: 'data_days', width: 80,
      render: days => (
        <Tooltip title={`基于${days || 0}天历史数据`}>
          <Badge
            status={(days || 0) >= 7 ? 'success' : (days || 0) >= 3 ? 'warning' : 'error'}
            text={`${days || 0}天`}
          />
        </Tooltip>
      ),
    },
    {
      title: '操作', key: 'action', width: 200,
      render: (_, record) => (
        <Space>
          <Button
            type="primary" size="small"
            style={{ background: '#CB11AB', borderColor: '#CB11AB' }}
            onClick={() => {
              const url = record.wb_backend_url || `https://cmp.wildberries.ru/campaigns/list/active/edit/${record.platform_campaign_id || record.campaign_id}`
              window.open(url, '_blank')
            }}
          >
            去WB改价
          </Button>
          <Button size="small" danger onClick={() => handleReject(record.id)}>
            忽略
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message="WB平台说明"
        description="Wildberries广告API暂不支持自动修改出价。AI将生成活动级别的调价建议，点击「去WB改价」直接跳转到WB卖家后台对应活动页面手动执行。企业微信也会同步推送建议。"
      />

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div style={{ fontSize: 15, fontWeight: 500 }}>
          待执行建议
          {suggestions.length > 0 && <Badge count={suggestions.length} style={{ marginLeft: 8 }} />}
        </div>
        <Button type="primary" loading={analyzing} icon={<RobotOutlined />} onClick={handleAnalyze}>
          立即分析
        </Button>
      </div>

      {suggestions.length === 0 ? (
        <Empty description="暂无调价建议，点击「立即分析」生成" style={{ padding: '40px 0' }} />
      ) : (
        <Table
          dataSource={suggestions}
          columns={columns}
          rowKey="id"
          loading={loading}
          pagination={false}
          scroll={{ x: 900 }}
          rowClassName={(record) => {
            const days = record.data_days || 0
            return days < 3 ? 'row-low-data' : ''
          }}
        />
      )}

      <style>{`.row-low-data { background: #fffbe6 !important; }`}</style>
    </div>
  )
}

// ==================== Ozon全自动模式 ====================

const OzonAIPricing = ({ shopId, platform = 'ozon' }) => {
  const bidLabel = platform === 'wb' ? 'CPM' : 'CPC'
  const [configs, setConfigs] = useState([])
  const [configsLoading, setConfigsLoading] = useState(false)
  const [editingConfig, setEditingConfig] = useState(null)
  const [configForm] = Form.useForm()
  const [configSubmitting, setConfigSubmitting] = useState(false)

  const [autoExecute, setAutoExecute] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)

  const [suggestions, setSuggestions] = useState([])
  const [suggestionsLoading, setSuggestionsLoading] = useState(false)
  const [suggestionsTotal, setSuggestionsTotal] = useState(0)
  const [suggestionsPage, setSuggestionsPage] = useState(1)

  const [selectedRowKeys, setSelectedRowKeys] = useState([])
  const [batchApproving, setBatchApproving] = useState(false)
  const [batchRejecting, setBatchRejecting] = useState(false)

  const [history, setHistory] = useState([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyTotal, setHistoryTotal] = useState(0)
  const [historyPage, setHistoryPage] = useState(1)
  const [historyDateRange, setHistoryDateRange] = useState(null)

  // 数据源管理
  const [dataStatus, setDataStatus] = useState(null)
  const [dataSyncing, setDataSyncing] = useState(false)

  // DeepSeek 流式分析弹窗
  const [streamOpen, setStreamOpen] = useState(false)
  const [streamPhase, setStreamPhase] = useState('')
  const [streamItems, setStreamItems] = useState([])
  const [streamHasError, setStreamHasError] = useState(false)
  const lastParsedRef = useRef(0)

  const extractSuggestions = (raw) => {
    const items = []
    const seen = new Set()
    const regex = /\{[^{}]*?"reason"\s*:\s*"[^"]*?"[^{}]*?\}/g
    let m
    while ((m = regex.exec(raw)) !== null) {
      try {
        const obj = JSON.parse(m[0])
        if (obj.platform_sku_id && obj.reason) {
          const key = `${obj.campaign_id || ''}_${obj.platform_sku_id}`
          if (seen.has(key)) continue
          seen.add(key)
          items.push(obj)
        }
      } catch { /* incomplete JSON */ }
    }
    return items
  }

  const loadDataStatus = useCallback(async () => {
    if (!shopId) return
    try {
      const res = await getDataStatus(shopId)
      setDataStatus(res.data)
    } catch {
      setDataStatus(null)
    }
  }, [shopId])

  const handleDataSync = async () => {
    setDataSyncing(true)
    try {
      const res = await syncData(shopId)
      const d = res?.data || {}
      if (d.background) {
        message.success('数据同步任务已提交，预计 10~20 分钟完成')
        setTimeout(() => loadDataStatus(), 60000)
      } else {
        message.success('数据同步完成')
        await loadDataStatus()
      }
    } catch (e) {
      message.error(e?.response?.data?.msg || e?.message || '同步失败')
    } finally {
      setDataSyncing(false)
    }
  }

  const handleDataDownload = async (days) => {
    try {
      const res = await downloadData(shopId, days)
      const url = URL.createObjectURL(new Blob([res]))
      const a = document.createElement('a')
      a.href = url
      a.download = `${platform || 'ads'}_data_${days}days.xlsx`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      message.error('下载失败')
    }
  }

  const fetchConfigs = useCallback(async () => {
    if (!shopId) return
    setConfigsLoading(true)
    try {
      const res = await getAIPricingConfigs(shopId)
      const data = res.data || []
      setConfigs(data)
      if (data.length > 0) setAutoExecute(!!data[0].auto_execute)
    } catch {
      setConfigs([])
    } finally {
      setConfigsLoading(false)
    }
  }, [shopId])

  const fetchSuggestions = useCallback(async (p = 1) => {
    if (!shopId) return
    setSuggestionsLoading(true)
    setSuggestionsPage(p)
    try {
      const res = await getAIPricingSuggestions(shopId, { status: 'pending' })
      // 后端按活动分组 {campaigns:[{campaign_id, campaign_name, suggestions:[...]}]}
      // 摊成"分组行 + 建议行"交织的行数组，供 Table 渲染树形分组
      const rows = []
      let total = 0
      ;(res.data?.campaigns || []).forEach(c => {
        const items = c.suggestions || []
        if (items.length === 0) return
        rows.push({
          key: `group-${c.campaign_id}`,
          isGroup: true,
          campaign_id: c.campaign_id,
          campaign_name: c.campaign_name,
          count: items.length,
        })
        items.forEach(s => {
          rows.push({
            key: `item-${s.id}`,
            isGroup: false,
            ...s,
            campaign_id: c.campaign_id,
            campaign_name: c.campaign_name,
          })
          total += 1
        })
      })
      setSuggestions(rows)
      setSuggestionsTotal(total)
    } catch {
      setSuggestions([])
      setSuggestionsTotal(0)
    } finally {
      setSuggestionsLoading(false)
    }
  }, [shopId])

  const fetchHistory = useCallback(async (p = 1) => {
    if (!shopId) return
    setHistoryLoading(true)
    setHistoryPage(p)
    try {
      const params = { page: p, page_size: 20 }
      if (historyDateRange && historyDateRange.length === 2) {
        params.start_date = historyDateRange[0].format('YYYY-MM-DD')
        params.end_date = historyDateRange[1].format('YYYY-MM-DD')
      }
      const res = await getAIPricingHistory(shopId, params)
      setHistory(res.data?.items || [])
      setHistoryTotal(res.data?.total || 0)
    } catch {
      setHistory([])
    } finally {
      setHistoryLoading(false)
    }
  }, [shopId, historyDateRange])

  useEffect(() => {
    fetchConfigs()
    fetchSuggestions()
    fetchHistory()
    loadDataStatus()
  }, [fetchConfigs, fetchSuggestions, fetchHistory, loadDataStatus])

  useEffect(() => {
    fetchHistory(1)
  }, [historyDateRange])

  const handleEditConfig = (record) => {
    setEditingConfig(record)
    configForm.setFieldsValue({
      gross_margin:           record.gross_margin          ?? 0.27,
      default_client_price:   record.default_client_price  ?? 600,
      max_bid:                record.max_bid               ?? 200,
      max_adjust_pct:         record.max_adjust_pct        ?? 30,
      auto_remove_losing_sku: !!record.auto_remove_losing_sku,
      losing_days_threshold:  record.losing_days_threshold ?? 21,
    })
  }

  const handleConfigSave = async () => {
    try {
      const values = await configForm.validateFields()
      setConfigSubmitting(true)
      const payload = {
        ...values,
        auto_remove_losing_sku: values.auto_remove_losing_sku ? 1 : 0,
        template_type: editingConfig?.template_type || 'default',
      }
      await updateAIPricingConfig(shopId, payload)
      message.success('配置已保存')
      setEditingConfig(null)
      fetchConfigs()
    } catch (err) {
      if (err.errorFields) return
      message.error(err.message || '保存失败')
    } finally {
      setConfigSubmitting(false)
    }
  }

  const handleToggleAuto = async (checked) => {
    try {
      await toggleAIAutoExecute(shopId, { auto_execute: checked })
      setAutoExecute(checked)
      message.success(checked ? '已切换为自动模式' : '已切换为建议模式')
      fetchConfigs()
    } catch (err) {
      message.error(err.message || '切换失败')
    }
  }

  const handleManualAnalyze = async () => {
    // 校验基础配置完整性
    const cfg = configs[0]
    if (!cfg || !cfg.gross_margin || !cfg.default_client_price) {
      Modal.warning({
        title: '基础配置未完成',
        content: '请先在「基础配置」里填写"默认净毛利率"和"默认客单价"，AI 才能计算每单广告上限。',
        okText: '去设置',
        onOk: () => cfg && handleEditConfig(cfg),
      })
      return
    }

    setAnalyzing(true)
    setStreamPhase('正在连接...')
    setStreamItems([])
    setStreamHasError(false)
    lastParsedRef.current = 0
    setStreamOpen(true)

    let fullText = ''
    try {
      const token = useAuthStore.getState().token
      const resp = await fetch(`/api/v1/bid-management/ai-pricing/${shopId}/analyze-stream`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        let eventType = ''
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim()
          } else if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))
              if (eventType === 'phase') {
                setStreamPhase(data)
              } else if (eventType === 'token') {
                fullText += data
                const parsed = extractSuggestions(fullText)
                if (parsed.length > lastParsedRef.current) {
                  lastParsedRef.current = parsed.length
                  setStreamItems([...parsed])
                }
              } else if (eventType === 'done') {
                setStreamPhase(data)
                fetchSuggestions(1)
              } else if (eventType === 'error') {
                setStreamPhase(`${data}`)
                setStreamHasError(true)
              }
            } catch { /* parse error */ }
          }
        }
      }
    } catch (err) {
      setStreamPhase(`分析失败：${err.message || err}`)
      message.error(err.message || '分析失败')
    } finally {
      setAnalyzing(false)
    }
  }

  const doApprove = async (id) => {
    try {
      await approveAIPricingSuggestion(id)
      message.success('已执行')
      fetchSuggestions(suggestionsPage)
      fetchHistory(1)
    } catch (err) {
      message.error(err.message || '执行失败')
    }
  }

  const handleApprove = (id) => {
    // 删除建议（从 handleDeleteConfirm 调过来）直接执行
    // 正常调价建议：弹确认框
    const record = suggestions.find(s => !s.isGroup && s.id === id)
    const isDelete = record && Number(record.suggested_bid) === 0 && Number(record.adjust_pct) === -100
    if (isDelete) {
      // 走真实 API（handleDeleteConfirm 已经弹过确认框）
      return doApprove(id)
    }

    if (!record) return doApprove(id)

    const isUp = Number(record.suggested_bid) > Number(record.old_bid ?? record.current_bid ?? 0)
    Modal.confirm({
      title: '确认执行该出价调整？',
      icon: <ExclamationCircleOutlined style={{ color: isUp ? '#cf1322' : '#389e0d' }} />,
      width: 460,
      content: (
        <div style={{ fontSize: 13, lineHeight: 1.8 }}>
          <div>
            商品：<strong>{record.sku_name || record.platform_sku_id}</strong>
            <span style={{ color: '#999', marginLeft: 6 }}>
              {record.platform_product_id ? `商品ID ${record.platform_product_id}` : ''}
              {record.product_code ? ` · 本地编码 ${record.product_code}` : ''}
            </span>
          </div>
          <div>活动：<strong>{record.campaign_name || `#${record.campaign_id}`}</strong></div>
          <div style={{
            marginTop: 10, padding: 10, borderRadius: 4,
            background: isUp ? '#fff2f0' : '#f6ffed',
            color: isUp ? '#cf1322' : '#389e0d',
            fontWeight: 500,
          }}>
            {isUp ? '加价' : '降价'} ₽{Math.round(Number(record.current_bid))} → ₽{Math.round(Number(record.suggested_bid))}
            <span style={{ marginLeft: 8, fontWeight: 400 }}>
              ({Number(record.adjust_pct) > 0 ? '+' : ''}{Number(record.adjust_pct).toFixed(2)}%)
            </span>
          </div>
          <div style={{ marginTop: 8, color: '#999', fontSize: 12 }}>
            执行后将调用平台 API 修改出价，生效立即计入 AI 调价历史。
          </div>
        </div>
      ),
      okText: '确认执行',
      okType: isUp ? 'danger' : 'primary',
      cancelText: '取消',
      onOk: () => doApprove(id),
    })
  }

  const handleDeleteConfirm = (record) => {
    Modal.confirm({
      title: '确认移除该商品出价？',
      icon: <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />,
      width: 460,
      content: (
        <div style={{ fontSize: 13, lineHeight: 1.8 }}>
          <div>
            商品：<strong>{record.sku_name || record.platform_sku_id}</strong>
            <span style={{ color: '#999', marginLeft: 6 }}>
              {record.platform_product_id ? `商品ID ${record.platform_product_id}` : ''}
              {record.product_code ? ` · 本地编码 ${record.product_code}` : ''}
            </span>
          </div>
          <div>活动：<strong>{record.campaign_name || `#${record.campaign_id}`}</strong></div>
          <div style={{ marginTop: 10, padding: 10, background: '#fff2f0', borderRadius: 4, color: '#cf1322' }}>
            删除后该商品将从活动列表中移除，此操作不可撤销。
          </div>
        </div>
      ),
      okText: '确认移除',
      okType: 'danger',
      cancelText: '取消',
      onOk: () => doApprove(record.id),
    })
  }

  const handleReject = async (id) => {
    try {
      await rejectAIPricingSuggestion(id)
      message.success('已忽略')
      fetchSuggestions(suggestionsPage)
    } catch (err) {
      message.error(err.message || '操作失败')
    }
  }

  const handleIgnore = (id) => {
    const record = suggestions.find(s => s.id === id)
    const skuName = record?.sku_name || record?.platform_sku_id || id
    Modal.confirm({
      title: '确认忽略该 SKU？',
      icon: <ExclamationCircleOutlined style={{ color: '#faad14' }} />,
      width: 460,
      content: (
        <div style={{ fontSize: 13, lineHeight: 1.8 }}>
          <div>
            商品：<strong>{skuName}</strong>
            {(record?.platform_product_id || record?.product_code) && (
              <span style={{ color: '#999', marginLeft: 6 }}>
                {record.platform_product_id ? `商品ID ${record.platform_product_id}` : ''}
                {record.product_code ? ` · 本地编码 ${record.product_code}` : ''}
              </span>
            )}
          </div>
          <div style={{ marginTop: 10, padding: 10, background: '#fffbe6', borderRadius: 4, color: '#874d00' }}>
            忽略后该 SKU <strong>长期不参与</strong> AI 自动调价和自动删除。<br />
            仍会在建议列表中显示 AI 推荐供参考，可随时点"恢复"重新启用。
          </div>
        </div>
      ),
      okText: '确认忽略',
      cancelText: '取消',
      onOk: async () => {
        try {
          await ignoreAIPricingSuggestion(id)
          message.success('已忽略该 SKU，不再参与自动调价')
          fetchSuggestions(suggestionsPage)
        } catch (err) {
          message.error(err.message || '操作失败')
        }
      },
    })
  }

  const handleRestore = async (id) => {
    try {
      await restoreAIPricingSuggestion(id)
      message.success('已恢复，重新参与自动调价')
      fetchSuggestions(suggestionsPage)
    } catch (err) {
      message.error(err.message || '操作失败')
    }
  }

  // rowKey 是 "item-{id}" 字符串，批量操作时拆出真实 id
  const extractIds = (keys) => keys
    .filter(k => typeof k === 'string' && k.startsWith('item-'))
    .map(k => Number(k.slice(5)))
    .filter(Boolean)

  const doBatchApprove = async (ids) => {
    setBatchApproving(true)
    try {
      const results = await Promise.allSettled(ids.map(id => approveAIPricingSuggestion(id)))
      const succeeded = results.filter(r => r.status === 'fulfilled').length
      const failed = results.filter(r => r.status === 'rejected').length
      if (failed > 0) {
        message.warning(`批量执行完成：${succeeded}条成功，${failed}条失败`)
      } else {
        message.success(`已批量执行 ${succeeded} 条建议`)
      }
      setSelectedRowKeys([])
      fetchSuggestions(1)
      fetchHistory(1)
    } catch (err) {
      message.error(err.message || '批量执行失败')
    } finally {
      setBatchApproving(false)
    }
  }

  const handleBatchApprove = () => {
    const ids = extractIds(selectedRowKeys)
    if (ids.length === 0) return

    // 统计批次构成：多少条调价、多少条删除
    const selectedRecords = suggestions.filter(r => !r.isGroup && ids.includes(r.id))
    const deleteCount = selectedRecords.filter(r =>
      Number(r.suggested_bid) === 0 && Number(r.adjust_pct) === -100
    ).length
    const adjustCount = ids.length - deleteCount

    Modal.confirm({
      title: `确认批量执行 ${ids.length} 条建议？`,
      icon: <ExclamationCircleOutlined style={{ color: '#faad14' }} />,
      width: 480,
      content: (
        <div style={{ fontSize: 13, lineHeight: 1.8 }}>
          <div style={{ marginBottom: 8 }}>
            本次批次包含：
          </div>
          {adjustCount > 0 && (
            <div>· <strong>{adjustCount}</strong> 条出价调整（直接调平台 API 改价）</div>
          )}
          {deleteCount > 0 && (
            <div style={{ color: '#cf1322' }}>
              · <strong>{deleteCount}</strong> 条商品移除（从活动里移除/降至最低出价，不可撤销）
            </div>
          )}
          <div style={{
            marginTop: 10, padding: 10, background: '#fffbe6',
            borderRadius: 4, color: '#d48806', fontSize: 12,
          }}>
            执行后所有改动会计入 AI 调价历史。部分失败的条目会在结果提示中显示。
          </div>
        </div>
      ),
      okText: `确认执行 (${ids.length})`,
      okType: deleteCount > 0 ? 'danger' : 'primary',
      cancelText: '取消',
      onOk: () => doBatchApprove(ids),
    })
  }

  const handleBatchReject = async () => {
    const ids = extractIds(selectedRowKeys)
    if (ids.length === 0) return
    setBatchRejecting(true)
    try {
      const results = await Promise.allSettled(ids.map(id => rejectAIPricingSuggestion(id)))
      const succeeded = results.filter(r => r.status === 'fulfilled').length
      const failed = results.filter(r => r.status === 'rejected').length
      if (failed > 0) {
        message.warning(`批量忽略完成：${succeeded}条成功，${failed}条失败`)
      } else {
        message.success(`已批量忽略 ${succeeded} 条建议`)
      }
      setSelectedRowKeys([])
      fetchSuggestions(1)
    } catch (err) {
      message.error(err.message || '批量忽略失败')
    } finally {
      setBatchRejecting(false)
    }
  }

  // 分组行在第一列渲染整行横幅（colSpan 跨所有列），其余列返回 colSpan:0 被合并
  const groupRowCell = (node) => ({ children: node, props: { colSpan: 12 } })
  const groupHiddenCell = () => ({ children: null, props: { colSpan: 0 } })

  const suggestionColumns = [
    {
      title: '商品名称', dataIndex: 'product_name', width: 220, ellipsis: true,
      render: (v, r) => {
        if (r.isGroup) {
          return groupRowCell(
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '6px 0', fontWeight: 500,
            }}>
              <span style={{
                display: 'inline-block', width: 3, height: 14,
                background: '#534AB7', borderRadius: 2,
              }} />
              <span>活动：{r.campaign_name || `#${r.campaign_id}`}</span>
              <Tag color="blue" style={{ marginLeft: 4 }}>{r.count} 条建议</Tag>
            </div>
          )
        }
        const name = v || r.sku_name || r.platform_sku_id || '-'
        const productUrl = r.product_url
          || (platform === 'wb' && r.platform_sku_id ? `https://www.wildberries.ru/catalog/${r.platform_sku_id}/detail.aspx` : null)
          || (platform === 'ozon' && r.platform_sku_id ? `https://www.ozon.ru/product/${r.platform_sku_id}` : null)
        const img = platform === 'wb'
          ? <WbProductImg nmId={r.platform_sku_id} size={36} />
          : (r.image_url
              ? <img src={r.image_url} alt="" style={{ width: 36, height: 36, borderRadius: 4, objectFit: 'cover', flexShrink: 0 }} />
              : <div style={{ width: 36, height: 36, borderRadius: 4, background: '#f0f0f0', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, color: '#bbb', flexShrink: 0 }}>无图</div>)
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {img}
            <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0, lineHeight: 1.3 }}>
              {r.is_ignored && (
                <Tag color="default" style={{ marginRight: 4, fontSize: 11 }}>🔒 已忽略</Tag>
              )}
              {productUrl ? (
                <a href={productUrl} target="_blank" rel="noopener noreferrer" style={{ fontSize: 13 }}>{name}</a>
              ) : <span style={{ fontSize: 13 }}>{name}</span>}
            </div>
          </div>
        )
      },
    },
    {
      title: '当前出价', dataIndex: 'current_bid', width: 90, align: 'right',
      render: (v, r) => r.isGroup ? groupHiddenCell() : `₽${Math.round(v)}`,
    },
    {
      title: `建议${bidLabel}`, dataIndex: 'suggested_bid', width: 90, align: 'right',
      render: (v, r) => {
        if (r.isGroup) return groupHiddenCell()
        if (Number(v) === 0 && Number(r.adjust_pct) === -100) {
          return <Tag color="red">删除</Tag>
        }
        return (
          <Text style={{ color: v > r.current_bid ? '#52c41a' : '#ff4d4f', fontWeight: 600 }}>
            ₽{Math.round(v)}
          </Text>
        )
      },
    },
    {
      title: '调幅', dataIndex: 'adjust_pct', width: 80, align: 'center',
      render: (v, r) => {
        if (r.isGroup) return groupHiddenCell()
        if (Number(v) === -100 && Number(r.suggested_bid) === 0) {
          return <Tag color="red">移除活动</Tag>
        }
        const isUp = v > 0
        return (
          <Tag color={isUp ? 'green' : 'red'} icon={isUp ? <ArrowUpOutlined /> : <ArrowDownOutlined />}>
            {isUp ? '+' : ''}{v}%
          </Tag>
        )
      },
    },
    {
      title: '数据质量', width: 90, align: 'center',
      render: (_, r) => {
        if (r.isGroup) return groupHiddenCell()
        const days = r.campaign_data_days || r.data_days || 0
        const isNew = r.is_new_campaign
        let status = 'success', text = '数据充足'
        if (isNew || days < 7) { status = 'error'; text = '数据不足' }
        else if (days < 14) { status = 'warning'; text = '数据有限' }
        return (
          <Tooltip title={isNew ? `新活动，仅${days}天数据，建议谨慎执行` : `基于${days}天历史数据`}>
            <Badge status={status} text={text} />
          </Tooltip>
        )
      },
    },
    {
      title: '决策依据', dataIndex: 'decision_basis', width: 100, align: 'center',
      render: (basis, r) => {
        if (r.isGroup) return groupHiddenCell()
        const DECISION_BASIS = {
          history_data: {
            color: 'blue', label: '历史数据',
            hint: 'SKU 自身数据 ≥ 7 天，主要按其历史 CTR / CR / ROAS 推算目标出价',
          },
          shop_benchmark: {
            color: 'green', label: '店铺基准',
            hint: 'SKU 自身数据 < 7 天（冷启动），借用店铺均值作为 CTR / CR 预估基线',
          },
          cold_start_baseline: {
            color: 'orange', label: '冷启动基准',
            hint: '完全无历史数据，使用类目冷启动兜底参数计算',
          },
          imported_data: {
            color: 'purple', label: '导入数据',
            hint: '基于人工导入的历史数据做判断',
          },
        }
        const cfg = DECISION_BASIS[basis] || { color: 'default', label: basis || '未知', hint: '未知决策来源' }
        const isDelete = Number(r.suggested_bid) === 0 && Number(r.adjust_pct) === -100
        const direction = isDelete
          ? { text: '建议移除', color: '#cf1322' }
          : (Number(r.adjust_pct) > 0
              ? { text: `建议涨价 +${r.adjust_pct}%`, color: '#cf1322' }
              : { text: `建议降价 ${r.adjust_pct}%`, color: '#389e0d' })
        return (
          <Tooltip
            color="#fff"
            overlayInnerStyle={{ color: '#333', maxWidth: 420 }}
            title={
              <div style={{ fontSize: 12, lineHeight: 1.7, padding: '4px 2px' }}>
                <div style={{ fontWeight: 600, marginBottom: 2 }}>{cfg.label}</div>
                <div style={{ color: '#666' }}>{cfg.hint}</div>
                <div style={{
                  margin: '8px 0 6px', padding: '4px 8px',
                  background: '#fafafa', borderLeft: `3px solid ${direction.color}`,
                  fontWeight: 500,
                }}>
                  {direction.text}
                  {!isDelete && (
                    <span style={{ color: '#999', fontWeight: 400, marginLeft: 6 }}>
                      ₽{Math.round(r.current_bid)} → ₽{Math.round(r.suggested_bid)}
                    </span>
                  )}
                </div>
                {r.reason && (
                  <div>
                    <div style={{ color: '#999', fontSize: 11, marginBottom: 2 }}>AI 计算理由：</div>
                    <div style={{ color: '#333' }}>{r.reason}</div>
                  </div>
                )}
              </div>
            }
          >
            <Tag color={cfg.color} style={{ cursor: 'help' }}>{cfg.label}</Tag>
          </Tooltip>
        )
      },
    },
    {
      title: 'ROAS', width: 110, align: 'right',
      render: (_, r) => r.isGroup ? groupHiddenCell() : (
        <span>
          {r.current_roas != null ? `${r.current_roas}x` : '-'}
          {r.expected_roas != null && (
            <Text style={{ color: r.expected_roas > (r.current_roas || 0) ? '#52c41a' : '#ff4d4f', marginLeft: 4 }}>
              →{r.expected_roas}x
            </Text>
          )}
        </span>
      ),
    },
    { ...stageColumn, render: (v, r) => r.isGroup ? groupHiddenCell() : stageColumn.render?.(v, r) },
    { ...optimizeColumn, render: (v, r) => r.isGroup ? groupHiddenCell() : optimizeColumn.render?.(v, r) },
    { ...promoColumn, render: (v, r) => r.isGroup ? groupHiddenCell() : promoColumn.render?.(v, r) },
    {
      title: 'AI理由', dataIndex: 'reason', ellipsis: { showTitle: false },
      render: (v, r) => r.isGroup ? groupHiddenCell() : <Tooltip title={v} placement="topLeft">{v}</Tooltip>,
    },
    {
      title: '操作', key: 'action', width: 160, fixed: 'right',
      render: (_, record) => {
        if (record.isGroup) return groupHiddenCell()
        // 被忽略的 SKU: 只显示"恢复"按钮
        if (record.is_ignored) {
          return (
            <Tooltip title="恢复后，该 SKU 重新参与 AI 自动调价和自动删除">
              <Button type="primary" size="small" onClick={() => handleRestore(record.id)}>
                恢复
              </Button>
            </Tooltip>
          )
        }
        const isDelete = Number(record.suggested_bid) === 0 && Number(record.adjust_pct) === -100
        return (
          <Space size="small">
            {isDelete ? (
              <Button danger size="small" onClick={() => handleDeleteConfirm(record)}>
                建议删除
              </Button>
            ) : (
              <Button type="primary" size="small" icon={<CheckOutlined />} onClick={() => handleApprove(record.id)}>
                执行
              </Button>
            )}
            <Tooltip title="忽略后，该 SKU 将长期不参与 AI 自动调价和自动删除，但仍会在建议列表中显示 AI 的推荐供参考。点击'恢复'可重新启用。">
              <Button size="small" icon={<CloseOutlined />} onClick={() => handleIgnore(record.id)}>
                忽略
              </Button>
            </Tooltip>
          </Space>
        )
      },
    },
  ]

  const EXECUTE_TYPE_CONFIG = {
    ai_auto:      { color: 'blue',    label: 'AI 自动' },
    ai_manual:    { color: 'cyan',    label: 'AI 建议确认' },
    auto_remove:  { color: 'red',     label: '亏损移除' },
    user_manual:  { color: 'default', label: '用户手动' },
    time_pricing: { color: 'purple',  label: '分时调价' },
    time_restore: { color: 'gold',    label: '分时恢复' },
  }

  const historyColumns = [
    {
      title: '时间', dataIndex: 'created_at', width: 130,
      render: v => v ? formatMoscowShort(v) : '-',
    },
    {
      title: '商品', dataIndex: 'sku_name', ellipsis: true,
      render: (v, r) => {
        const name = v || r.platform_sku_id || '-'
        const img = platform === 'wb'
          ? <WbProductImg nmId={r.platform_sku_id} size={28} />
          : null
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {img}
            <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>
              <div style={{ fontSize: 13 }}>{name}</div>
            </div>
          </div>
        )
      },
    },
    {
      title: '调整前', dataIndex: 'old_bid', width: 80, align: 'right',
      render: v => (v == null ? '-' : `₽${Math.round(Number(v))}`),
    },
    {
      title: '调整后', dataIndex: 'new_bid', width: 100, align: 'right',
      render: (v, r) => {
        if (v == null) return '-'
        const val = Number(v)
        const old = Number(r.old_bid ?? 0)
        const isDelete = val === 0 && Number(r.adjust_pct) === -100
        if (isDelete) return <Tag color="red">移除</Tag>
        return (
          <Text style={{ color: val > old ? '#cf1322' : '#389e0d', fontWeight: 500 }}>
            ₽{Math.round(val)}
          </Text>
        )
      },
    },
    {
      title: '调幅', dataIndex: 'adjust_pct', width: 80, align: 'center',
      render: v => {
        if (v == null) return '-'
        const val = Number(v)
        if (val === -100) return <Tag color="red">-100%</Tag>
        const isUp = val > 0
        return (
          <span style={{ color: isUp ? '#cf1322' : '#389e0d', fontSize: 12 }}>
            {isUp ? '+' : ''}{val.toFixed(2)}%
          </span>
        )
      },
    },
    {
      title: '执行方式', dataIndex: 'execute_type', width: 110, align: 'center',
      render: v => {
        const cfg = EXECUTE_TYPE_CONFIG[v] || { color: 'default', label: v || '未知' }
        return <Tag color={cfg.color}>{cfg.label}</Tag>
      },
    },
    {
      title: '状态', dataIndex: 'success', width: 90,
      render: (v, r) => {
        if (v) return <Tag color="green">成功</Tag>
        return (
          <Tooltip title={r.error_msg || '失败'}>
            <Tag color="red">失败</Tag>
          </Tooltip>
        )
      },
    },
  ]

  return (
    <div>
      {/* 策略模板配置（默认折叠） */}
      <Collapse style={{ marginBottom: 12 }} items={[{
        key: 'template-config',
        label: '基础配置',
        children: configsLoading ? <Card loading size="small" /> : configs.length > 0 ? (() => {
          const c = configs[0]
          const margin = c.gross_margin || 0
          const price  = c.default_client_price || 600
          const maxCpa = (price * margin).toFixed(0)
          return (
            <>
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '9px 12px',
                background: '#fafafa',
                borderRadius: 6,
                marginBottom: 10,
              }}>
                <span style={{ fontSize: 12, color: '#666' }}>
                  当前店铺策略 · 每单广告上限 <span style={{ color: '#ff4d4f', fontWeight: 500 }}>₽{maxCpa}</span>
                  <span style={{ color: '#999', marginLeft: 8 }}>（= 默认客单价 × 净毛利率）</span>
                </span>
                <Button size="small" type="primary" ghost icon={<EditOutlined />} onClick={() => handleEditConfig(c)}>
                  编辑
                </Button>
              </div>

              <div style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr 1fr',
                gap: 6,
              }}>
                {[
                  {
                    title: '默认净毛利率',
                    value: margin ? `${(margin * 100).toFixed(0)}%` : '-',
                    valueColor: '#1677ff',
                    hint: '扣除所有固定成本后的利润空间',
                  },
                  {
                    title: '默认客单价',
                    value: `₽${price}`,
                    valueColor: '#262626',
                    hint: '商品无价格数据时的兜底',
                  },
                  {
                    title: '自动删除亏损商品',
                    value: c.auto_remove_losing_sku ? '开启' : '关闭',
                    valueColor: c.auto_remove_losing_sku ? '#fa8c16' : '#999',
                    hint: c.auto_remove_losing_sku
                      ? `持续亏损超过 ${c.losing_days_threshold || 21} 天自动删除`
                      : '仅提醒不自动处理',
                  },
                ].map(item => (
                  <div key={item.title} style={{ background: '#fafafa', borderRadius: 6, padding: '10px 12px' }}>
                    <div style={{ fontSize: 11, fontWeight: 500, color: '#666', marginBottom: 4 }}>
                      {item.title}
                    </div>
                    <div style={{ fontSize: 20, fontWeight: 600, color: item.valueColor, lineHeight: 1.2, marginBottom: 2 }}>
                      {item.value}
                    </div>
                    <div style={{ fontSize: 11, color: '#999' }}>
                      {item.hint}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )
        })() : <Empty description="暂无基础配置" />,
      }]} />

      {/* 数据源管理（默认折叠） */}
      <Collapse style={{ marginBottom: 12 }} items={[{
        key: 'data',
        label: '数据源管理',
        children: (
          <>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '9px 12px',
              background: '#fafafa',
              borderRadius: 6,
              marginBottom: 10,
            }}>
              <span style={{ fontSize: 12, color: '#666' }}>
                上次同步：{dataStatus?.last_sync_at ? formatMoscowTime(dataStatus.last_sync_at) : '未同步'} ·
                数据范围：{dataStatus?.data_days || 0} 天
              </span>
              <Button type="primary" size="small" loading={dataSyncing} onClick={handleDataSync}>
                {dataSyncing ? '更新中...' : '更新数据源'}
              </Button>
            </div>

            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr 1fr',
              gap: 6,
              marginBottom: 10,
            }}>
              {[
                { title: '广告效果', items: ['CPM出价', '曝光量', '点击量/CTR', '订单数/CR', '收入/ROAS', '花费'] },
                { title: '时段分布', items: ['各小时花费', '各小时点击', '各小时转化'] },
                { title: '数据粒度', items: ['按活动维度', '按SKU维度', '按天汇总', '保留45天'] },
              ].map(group => (
                <div key={group.title} style={{ background: '#fafafa', borderRadius: 6, padding: '8px 10px' }}>
                  <div style={{ fontSize: 11, fontWeight: 500, color: '#666', marginBottom: 4 }}>
                    {group.title}
                  </div>
                  {group.items.map(item => (
                    <div key={item} style={{
                      fontSize: 11, color: '#262626', padding: '1px 0',
                      display: 'flex', alignItems: 'center', gap: 3,
                    }}>
                      <span style={{ width: 4, height: 4, borderRadius: '50%', background: '#534AB7', flexShrink: 0 }} />
                      {item}
                    </div>
                  ))}
                </div>
              ))}
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 12, color: '#666' }}>下载：</span>
              {[
                { label: '近7天', days: 7 },
                { label: '近1个月', days: 30 },
              ].map(item => (
                <Button key={item.days} size="small" onClick={() => handleDataDownload(item.days)}>
                  {item.label}
                </Button>
              ))}
              <Button size="small" onClick={() => handleDataDownload(45)}>
                近45天
              </Button>
              <span style={{ fontSize: 11, color: '#999' }}>Excel格式</span>
            </div>
          </>
        ),
      }]} />

      {/* 模式开关 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '16px 0' }}>
        <Switch checked={autoExecute} onChange={handleToggleAuto} />
        <span style={{ fontWeight: 500 }}>AI 智能调价</span>
        <span style={{ color: '#999', fontSize: 13 }}>
          {autoExecute ? '已开启' : '已关闭'}
        </span>
        <span style={{
          color: autoExecute ? '#52c41a' : '#faad14',
          fontSize: 12,
          marginLeft: 8,
        }}>
          {autoExecute
            ? '✓ AI 将自动调整出价（高峰 30 分钟 / 平稳 2 小时巡检）'
            : '✓ AI 将生成建议，需要你手动确认执行'}
        </span>
        <Button icon={<RobotOutlined />} onClick={handleManualAnalyze} loading={analyzing} style={{ marginLeft: 'auto' }}>
          立即分析
        </Button>
      </div>

      {/* DeepSeek 智能分析弹窗（流式） */}
      <Modal
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{
              width: 28, height: 28, borderRadius: '50%',
              background: 'linear-gradient(135deg, #7c6cf0, #534AB7)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: '#fff', fontSize: 12, fontWeight: 600,
            }}>AI</div>
            <span>DeepSeek 智能分析</span>
          </div>
        }
        open={streamOpen}
        footer={!analyzing ? (
          <Button type="primary" onClick={() => setStreamOpen(false)}>查看建议列表</Button>
        ) : null}
        closable={!analyzing}
        maskClosable={false}
        onCancel={() => setStreamOpen(false)}
        width={620}
      >
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '8px 12px', marginBottom: 12,
          background: analyzing ? '#f0ecff' : (streamHasError ? '#fff2f0' : '#f6ffed'),
          borderRadius: 6, fontSize: 13,
          color: analyzing ? '#534AB7' : (streamHasError ? '#cf1322' : '#389e0d'),
        }}>
          {analyzing && <Spin size="small" />}
          {!analyzing && streamHasError && <span style={{ fontSize: 16, fontWeight: 700 }}>×</span>}
          {!analyzing && !streamHasError && <span style={{ fontSize: 16 }}>&#10003;</span>}
          {streamPhase}
        </div>

        <div style={{ maxHeight: 420, overflowY: 'auto' }}>
          {streamItems.length === 0 && analyzing && (
            <div style={{ textAlign: 'center', padding: '40px 0', color: '#999', fontSize: 13 }}>
              AI 正在分析商品数据，建议将逐条出现...
            </div>
          )}
          {streamItems.map((item, idx) => {
            const isUp = item.suggested_bid > item.current_bid
            const stageMap = {
              growing: { color: 'green', label: '放量期' },
              declining: { color: 'red', label: '衰退期' },
              testing: { color: 'orange', label: '测试期' },
              cold_start: { color: 'blue', label: '冷启动' },
            }
            const stage = stageMap[item.product_stage] || { color: 'default', label: '数据不足' }
            return (
              <div key={idx} style={{
                border: '1px solid #f0f0f0',
                borderRadius: 8,
                padding: '12px 14px',
                marginBottom: 8,
                animation: 'fadeSlideIn 0.3s ease-out',
                background: '#fafafa',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                  <span style={{ fontSize: 13, fontWeight: 500, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {item.sku_name ? `${item.sku_name} · ${item.platform_sku_id}` : item.platform_sku_id}
                  </span>
                  <Tag color={stage.color} style={{ marginLeft: 8 }}>{stage.label}</Tag>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, marginBottom: 6 }}>
                  <span style={{ color: '#999' }}>出价</span>
                  <span style={{ fontWeight: 500 }}>₽{item.current_bid}</span>
                  <span style={{ color: isUp ? '#cf1322' : '#389e0d', fontSize: 16 }}>{isUp ? '↑' : '↓'}</span>
                  <span style={{ fontWeight: 600, color: isUp ? '#cf1322' : '#389e0d', fontSize: 15 }}>
                    ₽{item.suggested_bid}
                  </span>
                  {item.current_roas != null && (
                    <span style={{ color: '#999', marginLeft: 8, fontSize: 12 }}>ROAS {item.current_roas}x</span>
                  )}
                </div>
                {item.reason && (
                  <div style={{ fontSize: 12, color: '#666', lineHeight: 1.6 }}>
                    {item.reason}
                  </div>
                )}
              </div>
            )
          })}
          {!analyzing && streamItems.length > 0 && (
            <div style={{ textAlign: 'center', padding: '10px 0', color: '#999', fontSize: 12 }}>
              共 {streamItems.length} 条建议
            </div>
          )}
        </div>
        <style>{`
          @keyframes fadeSlideIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
          }
        `}</style>
      </Modal>

      {/* 待确认建议列表 */}
      {!autoExecute && (
        <Card
          title={`待确认建议 (${suggestionsTotal})`}
          size="small"
          style={{ marginBottom: 16 }}
          extra={
            suggestions.length > 0 && (
              <Space>
                <Button size="small" type="primary" loading={batchApproving}
                  disabled={selectedRowKeys.length === 0}
                  onClick={handleBatchApprove}>
                  批量执行 ({selectedRowKeys.length})
                </Button>
                <Button size="small" loading={batchRejecting}
                  disabled={selectedRowKeys.length === 0}
                  onClick={handleBatchReject}>
                  批量忽略 ({selectedRowKeys.length})
                </Button>
              </Space>
            )
          }
        >
          <style>{`
            .ai-suggestion-item-row > td.ant-table-selection-column {
              padding-left: 14px !important;
              padding-right: 0 !important;
              width: 40px !important;
            }
            .ai-suggestion-item-row > td:nth-child(2) {
              padding-left: 5px !important;
            }
            .ai-suggestion-group-row > td {
              background: #fafafa !important;
              border-bottom: 1px solid #e8e8e8 !important;
            }
            .ai-suggestion-group-row > td.ant-table-selection-column {
              padding-left: 14px !important;
            }
          `}</style>
          <Table
            size="small"
            dataSource={suggestions}
            rowKey="key"
            loading={suggestionsLoading}
            rowClassName={r => r.isGroup ? 'ai-suggestion-group-row' : 'ai-suggestion-item-row'}
            onRow={r => r.is_ignored ? { style: { background: '#fafafa', opacity: 0.75 } } : {}}
            rowSelection={{
              selectedRowKeys,
              onChange: setSelectedRowKeys,
              getCheckboxProps: r => ({ disabled: !!r.isGroup, style: r.isGroup ? { display: 'none' } : {} }),
            }}
            pagination={false}
            columns={suggestionColumns}
            scroll={{ x: 1200 }}
          />
        </Card>
      )}

      {/* 调价历史记录 */}
      <Collapse
        items={[{
          key: 'history',
          label: <span><HistoryOutlined /> 调价历史记录</span>,
          children: (
            <div>
              <div style={{ marginBottom: 12 }}>
                <RangePicker
                  value={historyDateRange}
                  onChange={setHistoryDateRange}
                  allowClear
                  presets={[
                    { label: '近7天', value: [dayjs().subtract(6, 'day'), dayjs()] },
                    { label: '近30天', value: [dayjs().subtract(29, 'day'), dayjs()] },
                  ]}
                />
              </div>
              <Table
                size="small"
                dataSource={history}
                rowKey="id"
                loading={historyLoading}
                pagination={{
                  current: historyPage,
                  total: historyTotal,
                  pageSize: 20,
                  size: 'small',
                  showTotal: t => `共 ${t} 条`,
                  onChange: p => fetchHistory(p),
                }}
                columns={historyColumns}
              />
            </div>
          ),
        }]}
      />

      {/* 模板编辑弹窗 */}
      <Modal
        title="编辑店铺策略"
        open={!!editingConfig}
        onOk={handleConfigSave}
        onCancel={() => setEditingConfig(null)}
        confirmLoading={configSubmitting}
        destroyOnClose
        width={560}
      >
        <Form form={configForm} layout="vertical" style={{ marginTop: 16 }}>

          {/* 盈利参数 */}
          <div style={{ fontWeight: 500, marginBottom: 12, color: '#333' }}>
            盈利参数
          </div>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="gross_margin"
                label={
                  <Tooltip
                    title={
                      <div style={{ lineHeight: 1.7 }}>
                        <div><strong>净毛利率（广义）</strong></div>
                        <div>= （售价 - 进货成本 - 平台佣金 - 物流 - 退货损耗）/ 售价</div>
                        <div>= 扣除所有固定成本后</div>
                        <div>= 广告费花出去之前的利润空间</div>
                      </div>
                    }
                  >
                    净毛利率 <span style={{ color: '#999', fontSize: 12 }}>（含佣金物流）</span>
                  </Tooltip>
                }
                rules={[
                  { required: true, message: '请输入净毛利率' },
                  { type: 'number', min: 0.01, max: 0.99, message: '请输入0.01~0.99之间的值' },
                ]}
              >
                <InputNumber
                  min={0.01} max={0.99} step={0.01}
                  style={{ width: '100%' }}
                  addonAfter="%"
                  formatter={v => v ? `${(v * 100).toFixed(0)}` : ''}
                  parser={v => v ? parseFloat(v) / 100 : 0}
                  placeholder="如：27 表示27%"
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="default_client_price"
                label={
                  <Tooltip title="商品无价格数据时使用此默认客单价，有数据时自动读取实际售价">
                    默认客单价 <span style={{ color: '#999', fontSize: 12 }}>（₽，无数据时兜底）</span>
                  </Tooltip>
                }
                rules={[{ required: true, message: '请输入默认客单价' }]}
              >
                <InputNumber
                  min={1} step={50}
                  style={{ width: '100%' }}
                  addonBefore="₽"
                  placeholder="如：600"
                />
              </Form.Item>
            </Col>
          </Row>

          {/* 系统自动计算提示 */}
          {(() => {
            const margin = configForm.getFieldValue('gross_margin')
            const price  = configForm.getFieldValue('default_client_price')
            if (!margin || !price) return null
            const maxCpa       = (price * margin).toFixed(0)
            const breakeven    = (1 / margin).toFixed(1)
            const targetCpa    = (price * margin * 0.6).toFixed(0)
            return (
              <Alert
                type="info"
                showIcon={false}
                style={{ marginBottom: 16, fontSize: 12 }}
                message={
                  <span>
                    系统自动计算：每单广告上限 <strong>₽{maxCpa}</strong>
                    &nbsp;·&nbsp;保本ROAS <strong>{breakeven}x</strong>
                    &nbsp;·&nbsp;利润最大化目标CPA <strong>₽{targetCpa}</strong>
                  </span>
                }
              />
            )
          })()}

          {/* 智能清理 */}
          <div style={{ fontWeight: 500, marginBottom: 12, color: '#333', marginTop: 8 }}>
            智能清理
          </div>
          <div style={{
            border: '1px solid #f0f0f0', borderRadius: 8,
            padding: '16px', background: '#fafafa',
          }}>
            <Form.Item
              name="auto_remove_losing_sku"
              valuePropName="checked"
              style={{ marginBottom: 8 }}
            >
              <Switch
                checkedChildren="已开启"
                unCheckedChildren="已关闭"
              />
            </Form.Item>
            <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 4 }}>
              自动删除持续亏损商品
            </div>
            <div style={{ fontSize: 12, color: '#999', lineHeight: 1.6, marginBottom: 12 }}>
              开启后，当商品广告数据超过观察期且持续亏损（ROAS低于保本线），
              系统将自动从广告活动中删除该商品的出价记录，并发送企业微信通知。
              <span style={{ color: '#ff4d4f' }}>此操作不可逆，请谨慎开启。</span>
            </div>
            <Form.Item
              noStyle
              shouldUpdate={(prev, curr) => prev.auto_remove_losing_sku !== curr.auto_remove_losing_sku}
            >
              {({ getFieldValue }) =>
                getFieldValue('auto_remove_losing_sku') ? (
                  <Form.Item
                    name="losing_days_threshold"
                    label="亏损观察天数"
                    style={{ marginBottom: 0 }}
                    extra="商品数据天数超过此值且持续亏损，才会触发自动删除"
                  >
                    <InputNumber
                      min={14} max={60} step={1}
                      style={{ width: 160 }}
                      addonAfter="天"
                    />
                  </Form.Item>
                ) : null
              }
            </Form.Item>
          </div>

          {/* 汇率提示 */}
          <Alert
            type="warning"
            showIcon={false}
            style={{ marginTop: 16, fontSize: 12 }}
            message="💡 提示：汇率波动时请及时更新净毛利率，平台佣金已包含在净毛利率中无需单独设置"
          />
        </Form>
      </Modal>
    </div>
  )
}

// ==================== 主入口：三平台统一页面 ====================

const AdsAIPricing = ({ shopId, platform, searched }) => {
  const tenant = useAuthStore(s => s.tenant)
  const tenantId = tenant?.id
  const platformInfo = PLATFORM_CONFIG[platform] || PLATFORM_CONFIG.ozon

  const [dataStatus, setDataStatus] = useState(null)
  const [checking, setChecking] = useState(true)
  const pollTimer = useRef(null)

  useEffect(() => {
    if (searched && shopId) {
      checkDataStatus()
    }
    return () => {
      if (pollTimer.current) clearInterval(pollTimer.current)
    }
  }, [shopId, searched])

  const checkDataStatus = async () => {
    setChecking(true)
    try {
      const res = await getDataStatus(shopId)
      setDataStatus(res.data)
      if (!res.data?.is_initialized) {
        pollTimer.current = setInterval(async () => {
          try {
            const r = await getDataStatus(shopId)
            if (r.data?.is_initialized) {
              setDataStatus(r.data)
              clearInterval(pollTimer.current)
            }
          } catch {
            /* 轮询失败静默，下次再试 */
          }
        }, 30000)
      }
    } catch {
      setDataStatus({ is_initialized: true })
    } finally {
      setChecking(false)
    }
  }

  if (!searched) {
    return <Card><Empty description="请选择平台和店铺后点击确定" /></Card>
  }

  if (checking) {
    return (
      <div style={{ textAlign: 'center', padding: '60px 0' }}>
        <Spin tip="检查数据状态..." />
      </div>
    )
  }

  if (dataStatus && !dataStatus.is_initialized) {
    return (
      <div style={{ textAlign: 'center', padding: '60px 0' }}>
        <Spin size="large" />
        <div style={{ marginTop: 24, fontSize: 16, fontWeight: 500 }}>
          正在拉取历史广告数据
        </div>
        <div style={{ marginTop: 8, color: '#999', fontSize: 14 }}>
          首次进入需要拉取近 14 天数据，约需 1-3 分钟
          <br />
          页面将自动刷新，请稍候...
        </div>
      </div>
    )
  }

  return (
    <div>
      {/* 平台标识栏：只读展示 */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
        marginBottom: 16, padding: '8px 12px',
        background: '#fafafa', borderRadius: 0,
        borderLeft: `3px solid ${platformInfo.color}`,
      }}>
        <Tag style={{ background: platformInfo.color, color: '#fff', border: 'none', fontWeight: 500, fontSize: 13 }}>
          {platformInfo.label}
        </Tag>
        <span style={{ fontSize: 13, color: '#999' }}>
          {platformInfo.description}
        </span>
        {platformInfo.mode === 'suggest' && (
          <Tag color="warning" style={{ marginLeft: 'auto' }}>建议模式</Tag>
        )}
        {platformInfo.mode === 'full' && (
          <Tag color="success" style={{ marginLeft: 'auto' }}>全自动可用</Tag>
        )}
      </div>

      {/* 大促状态提示条 */}
      <PromoStatusBar tenantId={tenantId} />

      {/* 根据platform渲染对应内容 */}
      {(platform === 'ozon' || platform === 'wb') && <OzonAIPricing shopId={shopId} platform={platform} />}
      {platform === 'yandex' && <YandexComingSoon />}

      {/* 大促日历管理 */}
      <PromoCalendarPanel tenantId={tenantId} />
    </div>
  )
}

export default AdsAIPricing
