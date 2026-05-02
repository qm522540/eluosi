import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Card, Table, Button, Space, Tag, Modal, Form, Select, InputNumber,
  Switch, message, Popconfirm, Tooltip, Typography,
} from 'antd'
import {
  PlusOutlined, ThunderboltOutlined, EyeOutlined, DeleteOutlined,
  PlayCircleOutlined, PauseCircleOutlined,
} from '@ant-design/icons'
import * as cloneApi from '@/api/clone'

const { Title, Text } = Typography

const CloneTaskList = () => {
  const navigate = useNavigate()
  const [tasks, setTasks] = useState([])
  const [shops, setShops] = useState([])
  const [loading, setLoading] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)
  const [scanningId, setScanningId] = useState(null)

  const loadTasks = async () => {
    setLoading(true)
    try {
      const r = await cloneApi.listTasks({ page: 1, size: 100 })
      setTasks(r.data?.items || [])
    } catch (e) {
      message.error(e.message || '加载任务失败')
    } finally {
      setLoading(false)
    }
  }

  const loadShops = async () => {
    try {
      const r = await cloneApi.listAvailableShops()
      setShops(r.data?.items || [])
    } catch (e) {
      message.error(e.message || '加载店铺列表失败')
    }
  }

  useEffect(() => {
    loadTasks()
    loadShops()
  }, [])

  const handleCreate = async (values) => {
    setSubmitting(true)
    try {
      await cloneApi.createTask({
        ...values,
        is_active: false,
      })
      message.success('任务已创建（默认未启用，请手动启用）')
      setCreateOpen(false)
      form.resetFields()
      loadTasks()
    } catch (e) {
      message.error(e.message || '创建失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleToggleActive = async (task) => {
    try {
      if (task.is_active) {
        await cloneApi.disableTask(task.id)
        message.success('已停用')
      } else {
        await cloneApi.enableTask(task.id)
        message.success('已启用')
      }
      loadTasks()
    } catch (e) {
      message.error(e.message || '操作失败')
    }
  }

  const handleScanNow = async (task) => {
    setScanningId(task.id)
    try {
      const r = await cloneApi.scanNow(task.id)
      const d = r.data
      Modal.success({
        title: '扫描完成',
        width: 480,
        content: (
          <div>
            <p>共扫描 B 店商品: <strong>{d.found || 0}</strong> 件</p>
            <p style={{ color: '#52c41a' }}>
              新增待审核: <strong>{d.new || 0}</strong> 件
            </p>
            <div style={{
              background: '#fafafa', padding: 8, marginTop: 8, fontSize: 13,
            }}>
              <div style={{ marginBottom: 4, color: '#666' }}>跳过明细:</div>
              <p style={{ margin: '2px 0' }}>· 已在审核队列（含已批准/失败）: {d.skip_pending || 0}</p>
              <p style={{ margin: '2px 0' }}>· 已发布到 A 店: {d.skip_published || 0}</p>
              <p style={{ margin: '2px 0' }}>· 之前被拒绝: {d.skip_rejected || 0}</p>
              <p style={{ margin: '2px 0' }}>· 类目映射缺失: {d.skip_category_missing || 0}</p>
            </div>
            {d.ai_rewrite_total > 0 && (
              <p style={{ marginTop: 8 }}>
                AI 改写: {d.ai_rewrite_total} 条 / 失败 {d.ai_rewrite_failed}
              </p>
            )}
            <p style={{ marginTop: 8, color: '#999', fontSize: 12 }}>耗时 {d.duration_ms} ms</p>
          </div>
        ),
      })
      loadTasks()
    } catch (e) {
      message.error(e.message || '扫描失败')
    } finally {
      setScanningId(null)
    }
  }

  const handleToggleFollowPrice = async (task, value) => {
    try {
      await cloneApi.updateTask(task.id, { follow_price_change: value })
      message.success(value ? '已开启跟价（B 改价 → A 自动同步）' : '已关闭跟价')
      loadTasks()
    } catch (e) {
      message.error(e.message || '操作失败')
    }
  }

  const handleDelete = async (task) => {
    try {
      await cloneApi.deleteTask(task.id)
      message.success('已删除')
      loadTasks()
    } catch (e) {
      message.error(e.message || '删除失败')
    }
  }

  const PLATFORM_COLOR = { ozon: 'blue', wb: 'magenta', yandex: 'gold' }
  const renderShop = (s) => {
    if (!s) return <Text type="secondary">-</Text>
    return (
      <Space size={4}>
        <Tag color={PLATFORM_COLOR[s.platform] || 'default'} style={{ marginInlineEnd: 0 }}>
          {s.platform}
        </Tag>
        <Text ellipsis style={{ maxWidth: 130 }}>{s.name}</Text>
      </Space>
    )
  }

  const columns = [
    {
      title: 'ID', dataIndex: 'id', width: 60, align: 'center',
    },
    {
      title: 'A 店 ← B 店', width: 240,
      render: (_, t) => (
        <div style={{ lineHeight: 1.6 }}>
          <div>{renderShop(t.target_shop)}</div>
          <div style={{ fontSize: 11, color: '#999' }}>← {renderShop(t.source_shop)}</div>
        </div>
      ),
    },
    {
      title: '状态', dataIndex: 'is_active', width: 70, align: 'center',
      render: (v) => v ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>,
    },
    {
      title: '配置', width: 200,
      render: (_, t) => (
        <Space size={[4, 2]} wrap>
          <Tooltip title={t.title_mode === 'ai_rewrite' ? '标题：AI 改写' : '标题：保留原文'}>
            <Tag color={t.title_mode === 'ai_rewrite' ? 'purple' : 'default'}>
              标题{t.title_mode === 'ai_rewrite' ? 'AI' : '原'}
            </Tag>
          </Tooltip>
          <Tooltip title={t.desc_mode === 'ai_rewrite' ? '描述：AI 改写' : '描述：保留原文'}>
            <Tag color={t.desc_mode === 'ai_rewrite' ? 'purple' : 'default'}>
              描述{t.desc_mode === 'ai_rewrite' ? 'AI' : '原'}
            </Tag>
          </Tooltip>
          <Tooltip title={t.price_mode === 'same' ? '价格：同 B 店' : `价格：B 店 × (1${t.price_adjust_pct >= 0 ? '+' : ''}${t.price_adjust_pct}%)`}>
            <Tag color={t.price_mode === 'same' ? 'default' : 'orange'}>
              {t.price_mode === 'same' ? '同价' : `${t.price_adjust_pct >= 0 ? '+' : ''}${t.price_adjust_pct}%`}
            </Tag>
          </Tooltip>
          <Tooltip title={t.follow_price_change
            ? 'B 改价 → A 自动跟改 (不走审核). 点击关闭'
            : '开启后, B 改价 → A 自动跟改 (不走审核)'}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <Switch size="small"
                checked={!!t.follow_price_change}
                onChange={(v) => handleToggleFollowPrice(t, v)} />
              <span style={{ fontSize: 12, color: t.follow_price_change ? '#1890ff' : '#999' }}>
                跟价
              </span>
            </span>
          </Tooltip>
        </Space>
      ),
    },
    {
      title: '上次扫描', width: 170,
      render: (_, t) => (
        <div style={{ lineHeight: 1.5 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t.last_check_at ? new Date(t.last_check_at).toLocaleString('zh-CN', { hour12: false }) : '从未'}
          </Text>
          {t.last_check_at && (
            <div style={{ fontSize: 11, marginTop: 2 }}>
              <Text type="success">新 {t.last_publish_count}</Text>
              <Text type="secondary"> · 跳 {t.last_skip_count}</Text>
            </div>
          )}
        </div>
      ),
    },
    {
      title: '待审 / 已发', width: 110, align: 'center',
      render: (_, t) => (
        <Space size={4}>
          <Tooltip title="点查看待审记录">
            <Button type="link" size="small" style={{ padding: '0 4px' }}
              onClick={() => navigate(`/clone/pending?task_id=${t.id}`)}>
              {t.pending_count || 0}
            </Button>
          </Tooltip>
          <Text type="secondary">/</Text>
          <Text>{t.published_count || 0}</Text>
        </Space>
      ),
    },
    {
      title: '操作', width: 170, fixed: 'right', align: 'center',
      render: (_, t) => (
        <Space size={2}>
          <Tooltip title={t.is_active ? '停用' : '启用'}>
            <Button size="small" type="text"
              icon={t.is_active ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
              onClick={() => handleToggleActive(t)} />
          </Tooltip>
          <Tooltip title="立即扫描">
            <Button size="small" type="primary" icon={<ThunderboltOutlined />}
              loading={scanningId === t.id}
              onClick={() => handleScanNow(t)} />
          </Tooltip>
          <Tooltip title="查看日志">
            <Button size="small" type="text" icon={<EyeOutlined />}
              onClick={() => navigate(`/clone/logs?task_id=${t.id}`)} />
          </Tooltip>
          <Popconfirm title="软删该任务？历史记录保留" onConfirm={() => handleDelete(t)}>
            <Tooltip title="删除">
              <Button size="small" type="text" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 16 }}>
      <Card
        title={<Title level={4} style={{ margin: 0 }}>克隆任务</Title>}
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            新建任务
          </Button>
        }
      >
        <Table
          rowKey="id" dataSource={tasks} columns={columns}
          loading={loading} scroll={{ x: 1020 }}
          size="middle"
          pagination={{ pageSize: 20 }}
        />
      </Card>

      <Modal
        title="新建克隆任务"
        open={createOpen}
        onOk={() => form.submit()}
        onCancel={() => { setCreateOpen(false); form.resetFields() }}
        confirmLoading={submitting}
        width={600}
      >
        <Form form={form} layout="vertical" onFinish={handleCreate}
          initialValues={{
            title_mode: 'original', desc_mode: 'original',
            price_mode: 'same', default_stock: 999,
            follow_price_change: false,
            category_strategy: 'use_local_map',
          }}>
          <Form.Item name="target_shop_id" label="A 店（落地店）"
            rules={[{ required: true, message: '请选择 A 店' }]}>
            <Select placeholder="选择 A 店"
              options={shops.map(s => ({ value: s.id, label: `${s.name} (${s.platform})` }))} />
          </Form.Item>
          <Form.Item name="source_shop_id" label="B 店（被跟踪店）"
            rules={[
              { required: true, message: '请选择 B 店' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || value !== getFieldValue('target_shop_id')) {
                    return Promise.resolve()
                  }
                  return Promise.reject(new Error('A 店和 B 店不能相同'))
                },
              }),
            ]}>
            <Select placeholder="选择 B 店"
              options={shops.map(s => ({ value: s.id, label: `${s.name} (${s.platform})` }))} />
          </Form.Item>
          <Form.Item name="title_mode" label="标题处理">
            <Select options={[
              { value: 'original', label: '保留 B 店原标题' },
              { value: 'ai_rewrite', label: 'AI 改写（复用 SEO 引擎）' },
            ]} />
          </Form.Item>
          <Form.Item name="desc_mode" label="描述处理">
            <Select options={[
              { value: 'original', label: '保留 B 店原描述' },
              { value: 'ai_rewrite', label: 'AI 改写（复用 SEO 引擎）' },
            ]} />
          </Form.Item>
          <Form.Item name="price_mode" label="价格策略">
            <Select options={[
              { value: 'same', label: '同 B 价' },
              { value: 'adjust_pct', label: '按百分比调价（如 +10% / -5%）' },
            ]} />
          </Form.Item>
          <Form.Item noStyle shouldUpdate>
            {({ getFieldValue }) =>
              getFieldValue('price_mode') === 'adjust_pct' ? (
                <Form.Item name="price_adjust_pct" label="价格调整百分比"
                  rules={[
                    { required: true, message: '请输入百分比' },
                    { type: 'number', min: -50, max: 200 },
                  ]}>
                  <InputNumber min={-50} max={200} step={1}
                    addonAfter="%" style={{ width: '100%' }} />
                </Form.Item>
              ) : null
            }
          </Form.Item>
          <Form.Item name="default_stock" label="A 店默认库存">
            <InputNumber min={0} max={999999} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="follow_price_change" label="跟价（B 改价后 A 自动调价，不走审核）"
            valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="category_strategy" label="跨平台类目映射策略">
            <Select options={[
              { value: 'use_local_map', label: '走本地映射库（缺失即跳过）' },
              { value: 'reject_if_missing', label: '映射缺失即拒（同上）' },
              { value: 'same_platform', label: '同平台直接复用（仅同平台）' },
            ]} />
          </Form.Item>
          <Text type="secondary" style={{ fontSize: 12 }}>
            创建后默认未启用，请在列表中手动启用。跨平台克隆需先在「映射管理」建好类目映射。
          </Text>
        </Form>
      </Modal>
    </div>
  )
}

export default CloneTaskList
