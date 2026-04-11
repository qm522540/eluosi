import { useState, useEffect } from 'react'
import {
  Typography, Card, Table, Button, Tag, Space, Select, Row, Col,
  Modal, Form, InputNumber, message, Empty,
  Switch, Divider,
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
  executeRules,
} from '@/api/ads'

const { Text } = Typography

const RULE_TYPES = {
  pause_low_roi: { label: '低ROI自动暂停', color: 'red' },
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
      // 传入当前选中的shopId，只执行该店铺下启用的规则
      const res = await executeRules(shopId)
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
            title: '操作', key: 'action', width: 120,
            render: (_, record) => (
              <Space size="small">
                <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEditRule(record)} />
                <Button type="link" size="small" danger icon={<DeleteOutlined />} onClick={() => handleDeleteRule(record.id)} />
              </Space>
            ),
          },
        ]}
      />

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
