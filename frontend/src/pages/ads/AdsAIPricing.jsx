import { useState, useEffect, useCallback } from 'react'
import {
  Typography, Card, Table, Button, Tag, Space, Row, Col,
  Modal, Form, InputNumber, message, Tooltip, Empty, Switch, Collapse, DatePicker,
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

const { Text, Title } = Typography
const { RangePicker } = DatePicker

const AdsAIPricing = ({ shopId, searched }) => {
  // 品类配置
  const [configs, setConfigs] = useState([])
  const [configsLoading, setConfigsLoading] = useState(false)
  const [editingConfig, setEditingConfig] = useState(null)
  const [configForm] = Form.useForm()
  const [configSubmitting, setConfigSubmitting] = useState(false)

  // 模式开关
  const [autoExecute, setAutoExecute] = useState(false)

  // AI分析
  const [analyzing, setAnalyzing] = useState(false)

  // 建议列表
  const [suggestions, setSuggestions] = useState([])
  const [suggestionsLoading, setSuggestionsLoading] = useState(false)
  const [suggestionsTotal, setSuggestionsTotal] = useState(0)
  const [suggestionsPage, setSuggestionsPage] = useState(1)

  // 批量操作
  const [selectedRowKeys, setSelectedRowKeys] = useState([])
  const [batchApproving, setBatchApproving] = useState(false)
  const [batchRejecting, setBatchRejecting] = useState(false)

  // 历史记录
  const [history, setHistory] = useState([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyTotal, setHistoryTotal] = useState(0)
  const [historyPage, setHistoryPage] = useState(1)
  const [historyDateRange, setHistoryDateRange] = useState(null)

  // ==================== 数据加载 ====================

  const fetchConfigs = useCallback(async () => {
    if (!shopId) return
    setConfigsLoading(true)
    try {
      const res = await getAIPricingConfigs(shopId)
      const data = res.data || []
      setConfigs(data)
      // 取第一个配置的auto_execute作为全局开关状态
      if (data.length > 0) {
        setAutoExecute(!!data[0].auto_execute)
      }
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
    if (searched && shopId) {
      fetchConfigs()
      fetchSuggestions()
      fetchHistory()
    }
  }, [searched, shopId, fetchConfigs, fetchSuggestions, fetchHistory])

  useEffect(() => {
    if (searched && shopId) fetchHistory(1)
  }, [historyDateRange, searched, shopId, fetchHistory])

  // ==================== 配置编辑 ====================

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

  // ==================== 模式切换 ====================

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

  // ==================== AI分析 ====================

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

  // ==================== 建议操作 ====================

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

  // ==================== 建议表格列 ====================

  const suggestionColumns = [
    {
      title: '商品名称', dataIndex: 'product_name', ellipsis: true,
      render: (v, r) => v || r.product_id || '-',
    },
    {
      title: '当前出价', dataIndex: 'current_bid', width: 100, align: 'right',
      render: v => `₽${v}`,
    },
    {
      title: '建议出价', dataIndex: 'suggested_bid', width: 100, align: 'right',
      render: (v, r) => (
        <Text style={{ color: v > r.current_bid ? '#52c41a' : '#ff4d4f', fontWeight: 600 }}>
          ₽{v}
        </Text>
      ),
    },
    {
      title: '调整幅度', dataIndex: 'adjust_pct', width: 100, align: 'center',
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
      title: '当前ROAS', dataIndex: 'current_roas', width: 95, align: 'right',
      render: v => v != null ? `${v}x` : '-',
    },
    {
      title: '预期ROAS', dataIndex: 'expected_roas', width: 95, align: 'right',
      render: (v, r) => {
        if (v == null) return '-'
        const isUp = v > (r.current_roas || 0)
        return (
          <Text style={{ color: isUp ? '#52c41a' : '#ff4d4f' }}>
            {v}x {isUp ? '↑' : '↓'}
          </Text>
        )
      },
    },
    {
      title: 'AI理由', dataIndex: 'reason', ellipsis: { showTitle: false },
      render: v => <Tooltip title={v} placement="topLeft">{v}</Tooltip>,
    },
    {
      title: '生成时间', dataIndex: 'created_at', width: 130,
      render: v => v ? dayjs(v).format('MM-DD HH:mm') : '-',
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

  // ==================== 历史表格列 ====================

  const historyColumns = [
    {
      title: '时间', dataIndex: 'created_at', width: 130,
      render: v => v ? dayjs(v).format('MM-DD HH:mm') : '-',
    },
    {
      title: '商品', dataIndex: 'product_name', ellipsis: true,
      render: (v, r) => v || r.product_id || '-',
    },
    {
      title: '调整前', dataIndex: 'current_bid', width: 90, align: 'right',
      render: v => `₽${v}`,
    },
    {
      title: '调整后', dataIndex: 'suggested_bid', width: 90, align: 'right',
      render: (v, r) => (
        <Text style={{ color: v > r.current_bid ? '#52c41a' : '#ff4d4f' }}>₽{v}</Text>
      ),
    },
    {
      title: '执行方式', dataIndex: 'auto_executed', width: 90, align: 'center',
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

  // ==================== 渲染 ====================

  if (!searched) {
    return <Card><Empty description="请选择平台和店铺后点击确定" /></Card>
  }

  return (
    <div>
      {/* 区域1：品类配置卡片 */}
      <Card title="品类调价配置" size="small" style={{ marginBottom: 16 }} loading={configsLoading}>
        {configs.length > 0 ? (
          <Table size="small" dataSource={configs} rowKey="id" pagination={false}
            columns={[
              { title: '品类', dataIndex: 'category_name', width: 100 },
              {
                title: <Tooltip title="广告ROAS的理想目标值，高于此值AI会建议加价抢量">目标ROAS</Tooltip>,
                dataIndex: 'target_roas', width: 90, align: 'right',
                render: v => `${v}x`,
              },
              {
                title: <Tooltip title="ROAS低于此值触发止损降价">最低ROAS</Tooltip>,
                dataIndex: 'min_roas', width: 90, align: 'right',
                render: v => `${v}x`,
              },
              {
                title: <Tooltip title="商品毛利率，用于计算盈亏平衡点">毛利率</Tooltip>,
                dataIndex: 'gross_margin', width: 80, align: 'right',
                render: v => `${(v * 100).toFixed(0)}%`,
              },
              {
                title: <Tooltip title="单日最大广告预算上限">日预算上限</Tooltip>,
                dataIndex: 'daily_budget_limit', width: 100, align: 'right',
                render: v => `₽${v}`,
              },
              {
                title: <Tooltip title="单次出价的最高限额">最高出价</Tooltip>,
                dataIndex: 'max_bid', width: 90, align: 'right',
                render: v => `₽${v}`,
              },
              {
                title: <Tooltip title="单次调价的最大比例">最大调幅</Tooltip>,
                dataIndex: 'max_adjust_pct', width: 90, align: 'right',
                render: v => `${v}%`,
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
        ) : <Empty description="暂无品类配置" />}
      </Card>

      {/* 区域2：模式开关 */}
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
            ? '✓ AI将自动调整出价，每小时执行一次'
            : '✓ AI将生成建议，需要你手动确认执行'}
        </span>
        <Button icon={<RobotOutlined />} onClick={handleManualAnalyze} loading={analyzing}>
          立即分析
        </Button>
      </div>

      {/* 区域3：待确认建议列表 */}
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
            rowSelection={{
              selectedRowKeys,
              onChange: setSelectedRowKeys,
            }}
            pagination={{
              current: suggestionsPage,
              total: suggestionsTotal,
              pageSize: 20,
              size: 'small',
              showTotal: t => `共 ${t} 条`,
              onChange: p => fetchSuggestions(p),
            }}
            columns={suggestionColumns}
            scroll={{ x: 1000 }}
          />
        </Card>
      )}

      {/* 区域4：调价历史记录 */}
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

      {/* ==================== 配置编辑弹窗 ==================== */}
      <Modal
        title={`编辑配置 — ${editingConfig?.category_name || ''}`}
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
                <Tooltip title="商品毛利率(0~1)，用于计算盈亏平衡">毛利率</Tooltip>
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

export default AdsAIPricing
