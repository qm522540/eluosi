import { useState, useEffect, useCallback } from 'react'
import {
  Typography, Card, Table, Button, Tag, Space, Row, Col,
  Modal, Form, InputNumber, message, Tooltip, Empty, Switch, Collapse, DatePicker, Avatar, Badge, Alert,
} from 'antd'
import {
  EditOutlined, CheckOutlined, CloseOutlined, RobotOutlined,
  ArrowUpOutlined, ArrowDownOutlined, HistoryOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  getAIPricingConfigs, updateAIPricingConfig,
  triggerAIAnalysis, getAIPricingSuggestions,
  approveAIPricingSuggestion, rejectAIPricingSuggestion,
  toggleAIAutoExecute, getAIPricingHistory,
} from '@/api/ads'
import { triggerWBAnalysis, getWBSuggestions, rejectWBSuggestion } from '@/api/wb_pricing'

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
    mode: 'suggest',
    description: '活动级别出价·需手动到WB后台执行',
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

const OzonAIPricing = ({ shopId }) => {
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
      const res = await getAIPricingSuggestions(shopId, { status: 'pending', page: p, page_size: 20 })
      setSuggestions(res.data?.items || [])
      setSuggestionsTotal(res.data?.total || 0)
    } catch {
      setSuggestions([])
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
  }, [fetchConfigs, fetchSuggestions, fetchHistory])

  useEffect(() => {
    fetchHistory(1)
  }, [historyDateRange])

  const handleEditConfig = (record) => {
    setEditingConfig(record)
    configForm.setFieldsValue({
      target_roas: record.target_roas,
      min_roas: record.min_roas,
      gross_margin: record.gross_margin,
      daily_budget_limit: record.daily_budget_limit,
      max_bid: record.max_bid,
      min_bid: record.min_bid,
      max_adjust_pct: record.max_adjust_pct,
    })
  }

  const handleConfigSave = async () => {
    try {
      const values = await configForm.validateFields()
      setConfigSubmitting(true)
      await updateAIPricingConfig(editingConfig.id, values)
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
    setAnalyzing(true)
    try {
      const res = await triggerAIAnalysis(shopId)
      const data = res.data || {}
      message.success(`分析完成：分析了 ${data.analyzed_count || 0} 个活动，生成 ${data.suggestion_count || 0} 条建议`)
      fetchSuggestions(1)
    } catch (err) {
      message.error(err.message || '分析失败')
    } finally {
      setAnalyzing(false)
    }
  }

  const handleApprove = async (id) => {
    try {
      await approveAIPricingSuggestion(id)
      message.success('已执行')
      fetchSuggestions(suggestionsPage)
      fetchHistory(1)
    } catch (err) {
      message.error(err.message || '执行失败')
    }
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

  const handleBatchApprove = async () => {
    if (selectedRowKeys.length === 0) return
    setBatchApproving(true)
    try {
      const results = await Promise.allSettled(selectedRowKeys.map(id => approveAIPricingSuggestion(id)))
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

  const handleBatchReject = async () => {
    if (selectedRowKeys.length === 0) return
    setBatchRejecting(true)
    try {
      const results = await Promise.allSettled(selectedRowKeys.map(id => rejectAIPricingSuggestion(id)))
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

  const suggestionColumns = [
    {
      title: '商品名称', dataIndex: 'product_name', width: 220, ellipsis: true,
      render: (v, r) => {
        const name = v || r.product_id || '-'
        const ozonUrl = r.product_id ? `https://www.ozon.ru/product/${r.product_id}` : null
        const img = r.image_url ? (
          <Avatar src={r.image_url} size={36} shape="square" style={{ marginRight: 8, flexShrink: 0 }} />
        ) : null
        return (
          <div style={{ display: 'flex', alignItems: 'center' }}>
            {img}
            <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {ozonUrl ? (
                <a href={ozonUrl} target="_blank" rel="noopener noreferrer">{name}</a>
              ) : name}
            </div>
          </div>
        )
      },
    },
    {
      title: '当前出价', dataIndex: 'current_bid', width: 90, align: 'right',
      render: v => `₽${Math.round(v)}`,
    },
    {
      title: '建议出价', dataIndex: 'suggested_bid', width: 90, align: 'right',
      render: (v, r) => (
        <Text style={{ color: v > r.current_bid ? '#52c41a' : '#ff4d4f', fontWeight: 600 }}>
          ₽{Math.round(v)}
        </Text>
      ),
    },
    {
      title: '调幅', dataIndex: 'adjust_pct', width: 80, align: 'center',
      render: (v) => {
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
      render: basis => ({
        'history_weighted': <Tag color="blue">历史数据</Tag>,
        'shop_benchmark': <Tag color="green">店铺基准</Tag>,
        'budget_control': <Tag color="orange">预算控制</Tag>,
        'today_only': <Tag>今日数据</Tag>,
      }[basis] || <Tag>{basis || '未知'}</Tag>),
    },
    {
      title: 'ROAS', width: 110, align: 'right',
      render: (_, r) => (
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
    {
      title: 'AI理由', dataIndex: 'reason', ellipsis: { showTitle: false },
      render: v => <Tooltip title={v} placement="topLeft">{v}</Tooltip>,
    },
    {
      title: '操作', key: 'action', width: 140, fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          <Button type="primary" size="small" icon={<CheckOutlined />} onClick={() => handleApprove(record.id)}>
            执行
          </Button>
          <Button size="small" icon={<CloseOutlined />} onClick={() => handleReject(record.id)}>
            忽略
          </Button>
        </Space>
      ),
    },
  ]

  const historyColumns = [
    {
      title: '时间', dataIndex: 'created_at', width: 130,
      render: v => v ? dayjs(v).format('MM-DD HH:mm') : '-',
    },
    {
      title: '商品', dataIndex: 'product_name', ellipsis: true,
      render: (v, r) => {
        const name = v || r.product_id || '-'
        const img = r.image_url ? (
          <Avatar src={r.image_url} size={28} shape="square" style={{ marginRight: 6, flexShrink: 0 }} />
        ) : null
        return (
          <div style={{ display: 'flex', alignItems: 'center' }}>
            {img}
            {name}
          </div>
        )
      },
    },
    {
      title: '调整前', dataIndex: 'current_bid', width: 80, align: 'right',
      render: v => `₽${Math.round(v)}`,
    },
    {
      title: '调整后', dataIndex: 'suggested_bid', width: 80, align: 'right',
      render: (v, r) => (
        <Text style={{ color: v > r.current_bid ? '#52c41a' : '#ff4d4f' }}>₽{Math.round(v)}</Text>
      ),
    },
    {
      title: '模板', dataIndex: 'template_name', width: 90, ellipsis: true,
      render: v => v || '-',
    },
    {
      title: '执行方式', dataIndex: 'auto_executed', width: 80, align: 'center',
      render: v => v ? <Tag color="blue">自动</Tag> : <Tag>手动</Tag>,
    },
    {
      title: '状态', dataIndex: 'status', width: 80,
      render: v => {
        const map = {
          executed: { color: 'green', text: '已执行' },
          rejected: { color: 'default', text: '已忽略' },
          expired: { color: 'orange', text: '已过期' },
        }
        const s = map[v] || { color: 'default', text: v }
        return <Tag color={s.color}>{s.text}</Tag>
      },
    },
  ]

  return (
    <div>
      {/* 策略模板配置 */}
      <Card title="策略模板配置" size="small" style={{ marginBottom: 16 }} loading={configsLoading}>
        {configs.length > 0 ? (
          <Table size="small" dataSource={configs} rowKey="id" pagination={false}
            columns={[
              {
                title: '模板名称', dataIndex: 'template_name', width: 160,
                render: (name, record) => (
                  <Space>
                    <Tag color={templateTypeConfig[record.template_type]?.color || 'default'}>
                      {templateTypeConfig[record.template_type]?.label || record.template_type}
                    </Tag>
                    <span style={{ fontWeight: 500 }}>{name}</span>
                  </Space>
                ),
              },
              {
                title: <Tooltip title="广告ROAS的理想目标值">目标ROAS</Tooltip>,
                dataIndex: 'target_roas', width: 90, align: 'right',
                render: v => `${v}x`,
              },
              {
                title: <Tooltip title="ROAS低于此值触发止损">最低ROAS</Tooltip>,
                dataIndex: 'min_roas', width: 90, align: 'right',
                render: v => `${v}x`,
              },
              {
                title: '最高出价', dataIndex: 'max_bid', width: 90, align: 'right',
                render: v => `₽${v}`,
              },
              {
                title: '日预算', dataIndex: 'daily_budget_limit', width: 100, align: 'right',
                render: (v, r) => r.no_budget_limit ? <Tag color="red">不限</Tag> : `₽${v}`,
              },
              {
                title: '说明', dataIndex: 'description', ellipsis: true,
              },
              {
                title: '操作', key: 'action', width: 70,
                render: (_, record) => (
                  <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEditConfig(record)}>
                    编辑
                  </Button>
                ),
              },
            ]}
          />
        ) : <Empty description="暂无策略模板" />}
      </Card>

      {/* 模式开关 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '16px 0' }}>
        <span style={{ fontWeight: 500 }}>AI自动执行</span>
        <Switch
          checked={autoExecute}
          onChange={handleToggleAuto}
          checkedChildren="自动模式"
          unCheckedChildren="建议模式"
        />
        <span style={{ color: autoExecute ? '#52c41a' : '#faad14', fontSize: 13 }}>
          {autoExecute
            ? '✓ AI将自动调整出价（高峰30分钟/平稳2小时巡检）'
            : '✓ AI将生成建议，需要你手动确认执行'}
        </span>
        <Button icon={<RobotOutlined />} onClick={handleManualAnalyze} loading={analyzing}>
          立即分析
        </Button>
      </div>

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
          <Table
            size="small"
            dataSource={suggestions}
            rowKey="id"
            loading={suggestionsLoading}
            rowSelection={{ selectedRowKeys, onChange: setSelectedRowKeys }}
            pagination={{
              current: suggestionsPage,
              total: suggestionsTotal,
              pageSize: 20,
              size: 'small',
              showTotal: t => `共 ${t} 条`,
              onChange: p => fetchSuggestions(p),
            }}
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
        title={`编辑模板 — ${editingConfig?.template_name || ''}`}
        open={!!editingConfig}
        onOk={handleConfigSave}
        onCancel={() => setEditingConfig(null)}
        confirmLoading={configSubmitting}
        destroyOnClose
      >
        <Form form={configForm} layout="vertical" style={{ marginTop: 16 }}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="target_roas" label={
                <Tooltip title="广告ROAS的理想目标值">目标ROAS</Tooltip>
              } rules={[{ required: true }]}>
                <InputNumber min={0.1} step={0.1} style={{ width: '100%' }} addonAfter="x" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="min_roas" label={
                <Tooltip title="低于此值触发止损降价">最低ROAS</Tooltip>
              } rules={[{ required: true }]}>
                <InputNumber min={0.1} step={0.1} style={{ width: '100%' }} addonAfter="x" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="gross_margin" label={
                <Tooltip title="商品毛利率(0~1)">毛利率</Tooltip>
              } rules={[{ required: true }]}>
                <InputNumber min={0.01} max={0.99} step={0.05} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="daily_budget_limit" label={
                <Tooltip title="单日最大广告花费限额">日预算上限 (₽)</Tooltip>
              } rules={[{ required: true }]}>
                <InputNumber min={1} step={100} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="max_bid" label={
                <Tooltip title="单次出价最高限额">最高出价 (₽)</Tooltip>
              } rules={[{ required: true }]}>
                <InputNumber min={1} step={10} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="min_bid" label={
                <Tooltip title="Ozon最低出价3卢布">最低出价 (₽)</Tooltip>
              }>
                <InputNumber min={1} step={1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="max_adjust_pct" label={
            <Tooltip title="单次调价的最大比例(1~100)">最大调整幅度 (%)</Tooltip>
          } rules={[{ required: true }]}>
            <InputNumber min={1} max={100} step={5} style={{ width: '100%' }} addonAfter="%" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

// ==================== 主入口：三平台统一页面 ====================

const AdsAIPricing = ({ shopId, platform, searched }) => {
  const [activePlatform, setActivePlatform] = useState(platform || 'ozon')
  const currentConfig = PLATFORM_CONFIG[activePlatform]

  useEffect(() => {
    if (platform) setActivePlatform(platform)
  }, [platform])

  if (!searched) {
    return <Card><Empty description="请选择平台和店铺后点击确定" /></Card>
  }

  return (
    <div>
      {/* 平台切换器 */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12,
        marginBottom: 20, padding: '12px 16px',
        background: '#fafafa', borderRadius: 8,
      }}>
        <span style={{ fontSize: 13, color: '#999' }}>当前平台</span>
        {Object.entries(PLATFORM_CONFIG).map(([key, cfg]) => (
          <Button
            key={key}
            type={activePlatform === key ? 'primary' : 'default'}
            size="small"
            style={{
              borderColor: cfg.color,
              color: activePlatform === key ? '#fff' : cfg.color,
              background: activePlatform === key ? cfg.color : 'transparent',
            }}
            onClick={() => setActivePlatform(key)}
          >
            {cfg.label}
          </Button>
        ))}
        <Tag color={
          currentConfig.mode === 'full' ? 'success' :
          currentConfig.mode === 'suggest' ? 'warning' : 'default'
        }>
          {currentConfig.mode === 'full' ? '全自动可用' :
           currentConfig.mode === 'suggest' ? '建议模式' : '即将上线'}
        </Tag>
        <span style={{ fontSize: 12, color: '#999' }}>
          {currentConfig.description}
        </span>
      </div>

      {/* 根据平台渲染不同内容 */}
      {activePlatform === 'ozon' && <OzonAIPricing shopId={shopId} />}
      {activePlatform === 'wb' && <WBAIPricing shopId={shopId} />}
      {activePlatform === 'yandex' && <YandexComingSoon />}
    </div>
  )
}

export default AdsAIPricing
