import { useState, useEffect } from 'react'
import {
  Typography, Card, Table, Button, Tag, Space, Select, Row, Col,
  Modal, Form, Input, InputNumber, message, Tooltip, Empty,
  Switch, Alert, Divider,
} from 'antd'
import {
  EditOutlined, PlusOutlined, DeleteOutlined, PlayCircleOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import timezone from 'dayjs/plugin/timezone'

dayjs.extend(utc)
dayjs.extend(timezone)
import {
  getAutomationRules, createAutomationRule, updateAutomationRule, deleteAutomationRule,
  executeRules, restoreRuleBids, getBidLogs,
} from '@/api/ads'
import { PLATFORMS } from '@/utils/constants'

const { Text } = Typography

const RULE_TYPES = {
  pause_low_roi: { label: '低ROI自动暂停', color: 'red' },
  auto_bid: { label: '分时自动调价', color: 'blue' },
  budget_cap: { label: '预算封顶', color: 'orange' },
}

const AdsRules = ({ shopId, platform, searched }) => {
  const [rules, setRules] = useState([])
  const [rulesLoading, setRulesLoading] = useState(false)
  const [ruleFormVisible, setRuleFormVisible] = useState(false)
  const [editingRule, setEditingRule] = useState(null)
  const [ruleForm] = Form.useForm()
  const [ruleSubmitting, setRuleSubmitting] = useState(false)
  const [executing, setExecuting] = useState(false)

  // 调价日志
  const [bidLogVisible, setBidLogVisible] = useState(false)
  const [bidLogRuleId, setBidLogRuleId] = useState(null)
  const [bidLogs, setBidLogs] = useState([])
  const [bidLogsLoading, setBidLogsLoading] = useState(false)
  const [bidLogsTotal, setBidLogsTotal] = useState(0)
  const [bidLogsPage, setBidLogsPage] = useState(1)

  const fetchRules = async () => {
    setRulesLoading(true)
    try {
      const params = {}
      if (shopId) params.shop_id = shopId
      const res = await getAutomationRules(params)
      setRules(res.data || [])
    } catch {
      setRules([])
    } finally {
      setRulesLoading(false)
    }
  }

  const fetchBidLogs = async (ruleId, p = 1) => {
    setBidLogsLoading(true)
    setBidLogsPage(p)
    try {
      const params = { page: p, page_size: 10 }
      if (ruleId) params.rule_id = ruleId
      const res = await getBidLogs(params)
      setBidLogs(res.data.items || [])
      setBidLogsTotal(res.data.total || 0)
    } catch {
      setBidLogs([])
    } finally {
      setBidLogsLoading(false)
    }
  }

  const handleShowBidLogs = (ruleId) => {
    setBidLogRuleId(ruleId)
    setBidLogVisible(true)
    fetchBidLogs(ruleId, 1)
  }

  useEffect(() => {
    if (searched) fetchRules()
  }, [searched, shopId])

  const handleCreateRule = () => {
    setEditingRule(null)
    ruleForm.resetFields()
    if (shopId) ruleForm.setFieldValue('shop_id', shopId)
    if (platform) ruleForm.setFieldValue('platform', platform)
    setRuleFormVisible(true)
  }

  const handleEditRule = (record) => {
    setEditingRule(record)
    const c = record.conditions || {}
    ruleForm.setFieldsValue({
      ...record,
      min_roas: c.min_roas,
      min_spend: c.min_spend,
      peak_hours: c.peak_hours,
      peak_pct: c.peak_pct,
      sub_peak_hours: c.sub_peak_hours,
      sub_peak_pct: c.sub_peak_pct,
      off_peak_hours: c.off_peak_hours,
      off_peak_pct: c.off_peak_pct,
      max_daily_spend: c.max_daily_spend,
    })
    setRuleFormVisible(true)
  }

  const handleRuleSubmit = async () => {
    try {
      const values = await ruleForm.validateFields()
      setRuleSubmitting(true)
      const ruleType = editingRule ? editingRule.rule_type : values.rule_type
      const conditions = {}
      const actions = {}
      if (ruleType === 'pause_low_roi') {
        conditions.min_roas = values.min_roas || 1.0
        conditions.min_spend = values.min_spend || 100
        actions.action = 'pause'
      } else if (ruleType === 'auto_bid') {
        conditions.peak_hours = values.peak_hours || [19, 20, 21]
        conditions.peak_pct = values.peak_pct ?? 30
        conditions.sub_peak_hours = values.sub_peak_hours || [22]
        conditions.sub_peak_pct = values.sub_peak_pct ?? 20
        conditions.off_peak_hours = values.off_peak_hours || [2, 3, 4, 5, 6]
        conditions.off_peak_pct = values.off_peak_pct ?? -50
        actions.action = 'time_bid'
      } else if (ruleType === 'budget_cap') {
        conditions.max_daily_spend = values.max_daily_spend || 5000
        actions.action = 'pause'
      }
      const payload = {
        name: RULE_TYPES[ruleType]?.label || ruleType,
        rule_type: ruleType,
        conditions,
        actions,
        platform: values.platform || platform || null,
        campaign_id: values.campaign_id || null,
        shop_id: shopId || null,
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

  const handleDeleteRule = (id) => {
    const rule = rules.find(r => r.id === id)
    if (rule?.rule_type === 'auto_bid' && rule?.actions?.original_bids) {
      Modal.confirm({
        title: '删除分时调价规则',
        content: '删除后将自动恢复所有商品的原始出价，确定继续？',
        okText: '确定删除并恢复出价',
        okType: 'danger',
        cancelText: '取消',
        onOk: async () => {
          try {
            await restoreRuleBids(id)
            await deleteAutomationRule(id)
            message.success('规则已删除，出价已恢复')
            fetchRules()
          } catch (err) {
            message.error(err.message || '操作失败')
          }
        },
      })
    } else {
      Modal.confirm({
        title: '确定删除此规则？',
        okText: '确定',
        okType: 'danger',
        cancelText: '取消',
        onOk: async () => {
          try {
            await deleteAutomationRule(id)
            message.success('规则已删除')
            fetchRules()
          } catch (err) {
            message.error(err.message || '删除失败')
          }
        },
      })
    }
  }

  const handleToggleRule = (record) => {
    if (record.rule_type === 'auto_bid' && record.enabled && record.actions?.original_bids) {
      Modal.confirm({
        title: '关闭分时调价规则',
        content: '关闭后将自动恢复所有商品的原始出价，确定继续？',
        okText: '确定关闭并恢复出价',
        cancelText: '取消',
        onOk: async () => {
          try {
            await restoreRuleBids(record.id)
            await updateAutomationRule(record.id, { enabled: 0 })
            message.success('规则已禁用，出价已恢复')
            fetchRules()
          } catch (err) {
            message.error(err.message || '操作失败')
          }
        },
      })
    } else {
      (async () => {
        try {
          await updateAutomationRule(record.id, { enabled: record.enabled ? 0 : 1 })
          message.success(record.enabled ? '规则已禁用' : '规则已启用')
          fetchRules()
        } catch (err) {
          message.error(err.message || '操作失败')
        }
      })()
    }
  }

  const handleExecuteRules = async () => {
    setExecuting(true)
    try {
      const res = await executeRules()
      message.success(`规则执行完成，检查了 ${res.data?.rules_checked || 0} 条规则`)
      fetchRules()
    } catch (err) {
      message.error(err.message || '执行失败')
    } finally {
      setExecuting(false)
    }
  }

  // 计算下次执行时间（莫斯科时间每小时的第25分钟）
  const getNextExecTime = () => {
    const now = dayjs().tz('Europe/Moscow')
    let next = now.minute() < 25
      ? now.minute(25).second(0)
      : now.add(1, 'hour').minute(25).second(0)
    return next
  }

  if (!searched) {
    return <Card><Empty description="请选择平台和店铺后点击确定" /></Card>
  }

  return (
    <>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Text>
          当前莫斯科时间：<Text strong>{dayjs().tz('Europe/Moscow').format('HH:mm')}</Text>，
          系统每小时 :25 分自动执行，
          下次执行：<Text strong>{getNextExecTime().format('HH:mm')}</Text>
        </Text>
        <Space>
          <Button icon={<PlayCircleOutlined />} loading={executing} onClick={handleExecuteRules}>立即执行</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleCreateRule}>新建规则</Button>
        </Space>
      </div>

      <Table size="small" dataSource={rules} rowKey="id" loading={rulesLoading} pagination={false}
        columns={[
          {
            title: '规则类型', dataIndex: 'rule_type', width: 160,
            render: v => <Tag color={RULE_TYPES[v]?.color}>{RULE_TYPES[v]?.label || v}</Tag>,
          },
          {
            title: '条件', key: 'conditions', ellipsis: true,
            render: (_, r) => {
              const c = r.conditions || {}
              if (r.rule_type === 'pause_low_roi') return `ROAS < ${c.min_roas || 1}，花费 >= ₽${c.min_spend || 100}`
              if (r.rule_type === 'auto_bid') return `高峰+${c.peak_pct||30}% | 次峰+${c.sub_peak_pct||20}% | 低谷${c.off_peak_pct||-50}%`
              if (r.rule_type === 'budget_cap') return `日花费上限 ₽${c.max_daily_spend || 0}`
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
            title: '最后触发', dataIndex: 'last_triggered_at', width: 130,
            render: v => v ? dayjs(v).format('MM-DD HH:mm') : '-',
          },
          {
            title: '下次执行', key: 'next_exec', width: 130,
            render: (_, r) => r.enabled
              ? <Text type="success">{getNextExecTime().format('HH:mm')} (莫斯科)</Text>
              : <Text type="secondary">已停用</Text>,
          },
          {
            title: '操作', key: 'action', width: 160,
            render: (_, record) => (
              <Space size="small">
                {record.rule_type === 'auto_bid' && (
                  <Button type="link" size="small" onClick={() => handleShowBidLogs(record.id)}>日志</Button>
                )}
                <Tooltip title={record.rule_type === 'auto_bid' && record.enabled ? '请先关闭规则再编辑' : ''}>
                  <Button type="link" size="small" icon={<EditOutlined />}
                    disabled={record.rule_type === 'auto_bid' && !!record.enabled}
                    onClick={() => handleEditRule(record)} />
                </Tooltip>
                <Button type="link" size="small" danger icon={<DeleteOutlined />} onClick={() => handleDeleteRule(record.id)} />
              </Space>
            ),
          },
        ]}
      />

      {/* ==================== 调价日志弹窗 ==================== */}
      <Modal
        title="调价日志"
        open={bidLogVisible}
        onCancel={() => setBidLogVisible(false)}
        footer={null}
        width={800}
      >
        <Table size="small" dataSource={bidLogs} rowKey="id" loading={bidLogsLoading}
          pagination={{
            current: bidLogsPage, total: bidLogsTotal, pageSize: 10, size: 'small',
            onChange: (p) => fetchBidLogs(bidLogRuleId, p),
          }}
          columns={[
            { title: '时间', dataIndex: 'created_at', width: 130, render: v => v ? dayjs(v).format('MM-DD HH:mm') : '-' },
            { title: '活动', dataIndex: 'campaign_name', ellipsis: true, render: (v, r) => <Tooltip title={`ID: ${r.campaign_id}`}>{v || r.campaign_id}</Tooltip> },
            { title: '平台', dataIndex: 'platform', width: 100, render: p => <Tag color={PLATFORMS[p]?.color}>{PLATFORMS[p]?.label || p}</Tag> },
            { title: '广告组', dataIndex: 'group_name', width: 110, ellipsis: true },
            { title: '原出价', dataIndex: 'old_bid', width: 75, align: 'right', render: v => `₽${v}` },
            { title: '新出价', dataIndex: 'new_bid', width: 75, align: 'right', render: (v, r) => <Text style={{ color: r.change_pct > 0 ? '#52c41a' : '#ff4d4f' }}>₽{v}</Text> },
            { title: '调幅', dataIndex: 'change_pct', width: 65, align: 'center', render: v => <Tag color={v > 0 ? 'green' : 'red'}>{v > 0 ? '+' : ''}{v}%</Tag> },
            { title: '原因', dataIndex: 'reason', ellipsis: true },
          ]}
        />
      </Modal>

      {/* ==================== 自动化规则 表单弹窗 ==================== */}
      <Modal
        title={editingRule ? `编辑规则 — ${RULE_TYPES[editingRule.rule_type]?.label}` : '新建自动化规则'}
        open={ruleFormVisible}
        onOk={handleRuleSubmit}
        onCancel={() => setRuleFormVisible(false)}
        confirmLoading={ruleSubmitting}
        destroyOnClose
        width={600}
      >
        <Form form={ruleForm} layout="vertical" style={{ marginTop: 16 }}>
          <Row gutter={16}>
            {!editingRule && (
              <Col span={16}>
                <Form.Item name="rule_type" label="规则类型" rules={[{ required: true, message: '请选择规则类型' }]}>
                  <Select options={Object.entries(RULE_TYPES).map(([k, v]) => ({ value: k, label: v.label }))} />
                </Form.Item>
              </Col>
            )}
            <Col span={editingRule ? 24 : 8}>
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
                <div>
                  <Alert message="根据莫斯科时间自动调整出价，高峰加价抢流量，低谷降价省预算" type="info" showIcon style={{ marginBottom: 16 }} />
                  <Form.Item noStyle shouldUpdate={(prev, cur) =>
                    prev.peak_hours !== cur.peak_hours || prev.sub_peak_hours !== cur.sub_peak_hours || prev.off_peak_hours !== cur.off_peak_hours
                  }>
                    {({ getFieldValue }) => {
                      const peakH = getFieldValue('peak_hours') || []
                      const subPeakH = getFieldValue('sub_peak_hours') || []
                      const offPeakH = getFieldValue('off_peak_hours') || []
                      const hourOpts = (excludeA, excludeB) => {
                        const used = new Set([...excludeA, ...excludeB])
                        return Array.from({ length: 24 }, (_, i) => ({
                          value: i, label: `${i}:00`, disabled: used.has(i),
                        }))
                      }
                      return (
                        <>
                          <Card size="small" title="高峰时段" style={{ marginBottom: 12, borderLeft: '3px solid #ff4d4f' }}>
                            <Row gutter={16}>
                              <Col span={16}>
                                <Form.Item name="peak_hours" label="时间范围" initialValue={[19,20,21]}>
                                  <Select mode="multiple" placeholder="选择小时" options={hourOpts(subPeakH, offPeakH)} />
                                </Form.Item>
                              </Col>
                              <Col span={8}>
                                <Form.Item name="peak_pct" label="加价比例(%)" initialValue={30}>
                                  <InputNumber min={0} max={200} style={{ width: '100%' }} addonAfter="%" />
                                </Form.Item>
                              </Col>
                            </Row>
                          </Card>
                          <Card size="small" title="次高峰时段" style={{ marginBottom: 12, borderLeft: '3px solid #faad14' }}>
                            <Row gutter={16}>
                              <Col span={16}>
                                <Form.Item name="sub_peak_hours" label="时间范围" initialValue={[22]}>
                                  <Select mode="multiple" placeholder="选择小时" options={hourOpts(peakH, offPeakH)} />
                                </Form.Item>
                              </Col>
                              <Col span={8}>
                                <Form.Item name="sub_peak_pct" label="加价比例(%)" initialValue={20}>
                                  <InputNumber min={0} max={200} style={{ width: '100%' }} addonAfter="%" />
                                </Form.Item>
                              </Col>
                            </Row>
                          </Card>
                          <Card size="small" title="低谷时段" style={{ marginBottom: 12, borderLeft: '3px solid #1890ff' }}>
                            <Row gutter={16}>
                              <Col span={16}>
                                <Form.Item name="off_peak_hours" label="时间范围" initialValue={[2,3,4,5,6]}>
                                  <Select mode="multiple" placeholder="选择小时" options={hourOpts(peakH, subPeakH)} />
                                </Form.Item>
                              </Col>
                              <Col span={8}>
                                <Form.Item name="off_peak_pct" label="降价比例(%)" initialValue={-50}>
                                  <InputNumber min={-90} max={0} style={{ width: '100%' }} addonAfter="%" />
                                </Form.Item>
                              </Col>
                            </Row>
                          </Card>
                        </>
                      )
                    }}
                  </Form.Item>
                  <Text type="secondary">其他未设置的时段将保持原始出价不变。系统每小时（莫斯科时间 :25 分）自动执行。</Text>
                </div>
              )
              if (rt === 'budget_cap') return (
                <Form.Item name="max_daily_spend" label="日花费上限(₽)" initialValue={5000}>
                  <InputNumber min={100} step={500} style={{ width: '100%' }} />
                </Form.Item>
              )
              return <Text type="secondary">请先选择规则类型</Text>
            }}
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

export default AdsRules
