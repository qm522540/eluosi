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
        content: (
          <div>
            <p>共扫描: {d.found} 件</p>
            <p style={{ color: 'green' }}>新增待审核: {d.new}</p>
            <p>已发布跳过: {d.skip_published}</p>
            <p>已拒绝跳过: {d.skip_rejected}</p>
            <p>类目映射缺失跳过: {d.skip_category_missing}</p>
            {d.ai_rewrite_total > 0 && (
              <p>AI 改写: {d.ai_rewrite_total} 条 / 失败 {d.ai_rewrite_failed}</p>
            )}
            <p>耗时: {d.duration_ms} ms</p>
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

  const handleDelete = async (task) => {
    try {
      await cloneApi.deleteTask(task.id)
      message.success('已删除')
      loadTasks()
    } catch (e) {
      message.error(e.message || '删除失败')
    }
  }

  const columns = [
    {
      title: 'ID', dataIndex: 'id', width: 60,
    },
    {
      title: 'A 店（落地）', dataIndex: 'target_shop',
      render: (s) => s ? `${s.name} (${s.platform})` : '-',
    },
    {
      title: 'B 店（被跟踪）', dataIndex: 'source_shop',
      render: (s) => s ? `${s.name} (${s.platform})` : '-',
    },
    {
      title: '状态', dataIndex: 'is_active', width: 80,
      render: (v) => v ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>,
    },
    {
      title: '配置', width: 220,
      render: (_, t) => (
        <Space size={4} wrap>
          <Tag>{t.title_mode === 'ai_rewrite' ? '标题AI' : '标题原文'}</Tag>
          <Tag>{t.desc_mode === 'ai_rewrite' ? '描述AI' : '描述原文'}</Tag>
          <Tag>{t.price_mode === 'same' ? '同价' : `${t.price_adjust_pct >= 0 ? '+' : ''}${t.price_adjust_pct}%`}</Tag>
          {t.follow_price_change ? <Tag color="blue">跟价</Tag> : null}
        </Space>
      ),
    },
    {
      title: '上次扫描', width: 240,
      render: (_, t) => (
        <div>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t.last_check_at ? new Date(t.last_check_at).toLocaleString() : '从未'}
          </Text>
          {t.last_check_at && (
            <div style={{ fontSize: 12 }}>
              <Tag color="green" style={{ marginInlineEnd: 4 }}>新 {t.last_publish_count}</Tag>
              <Tag style={{ marginInlineEnd: 4 }}>跳 {t.last_skip_count}</Tag>
            </div>
          )}
        </div>
      ),
    },
    {
      title: '待审 / 已发布', width: 130,
      render: (_, t) => (
        <Space>
          <Tooltip title="点查看待审">
            <Button type="link" size="small"
              onClick={() => navigate(`/clone/pending?task_id=${t.id}`)}>
              待审 {t.pending_count || 0}
            </Button>
          </Tooltip>
          <Text type="secondary">/ {t.published_count || 0}</Text>
        </Space>
      ),
    },
    {
      title: '操作', width: 280, fixed: 'right',
      render: (_, t) => (
        <Space size={4}>
          <Button size="small"
            icon={t.is_active ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
            onClick={() => handleToggleActive(t)}>
            {t.is_active ? '停用' : '启用'}
          </Button>
          <Button size="small" type="primary" icon={<ThunderboltOutlined />}
            loading={scanningId === t.id}
            onClick={() => handleScanNow(t)}>
            立即扫描
          </Button>
          <Button size="small" icon={<EyeOutlined />}
            onClick={() => navigate(`/clone/logs?task_id=${t.id}`)}>
            日志
          </Button>
          <Popconfirm title="软删该任务？历史记录保留" onConfirm={() => handleDelete(t)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
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
          loading={loading} scroll={{ x: 1200 }}
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
