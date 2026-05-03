import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Card, Table, Button, Space, Tag, Modal, Form, Select, InputNumber, Input,
  Switch, message, Popconfirm, Tooltip, Typography, Checkbox, Image, Badge, Spin,
} from 'antd'
import {
  PlusOutlined, ThunderboltOutlined, EyeOutlined, DeleteOutlined,
  PlayCircleOutlined, PauseCircleOutlined, CheckCircleOutlined,
  ArrowLeftOutlined, ClockCircleOutlined, EditOutlined,
} from '@ant-design/icons'

// 简单相对时间 helper
const relativeTime = (iso) => {
  if (!iso) return '从未'
  const ms = Date.now() - new Date(iso).getTime()
  if (ms < 0) return '刚刚'
  const min = Math.floor(ms / 60000)
  if (min < 1) return '刚刚'
  if (min < 60) return `${min} 分钟前`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} 小时前`
  const d = Math.floor(hr / 24)
  if (d < 30) return `${d} 天前`
  return `${Math.floor(d / 30)} 个月前`
}
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
  // 编辑任务 Modal
  const [editTask, setEditTask] = useState(null)
  const [editForm] = Form.useForm()
  const [editSubmitting, setEditSubmitting] = useState(false)
  // 11.2 扫描预览 Modal
  // localSkus: { [source_sku_id]: 用户改过的本地 SKU }; 默认 = source_sku_id, 用户可改
  const [previewState, setPreviewState] = useState({
    open: false, task: null, candidates: [], stats: {}, selectedSkus: new Set(),
    localSkus: {}, confirming: false,
  })

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
      // 简化设计 (老板拍): 创建即启用, 省"先创建再启用"一步
      await cloneApi.createTask({
        ...values,
        is_active: true,
      })
      message.success('任务已创建并启用，可点 ⚡ 立即扫描')
      setCreateOpen(false)
      form.resetFields()
      loadTasks()
    } catch (e) {
      message.error(e.message || '创建失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleOpenEdit = (task) => {
    setEditTask(task)
    editForm.setFieldsValue({
      title_mode: task.title_mode || 'original',
      desc_mode: task.desc_mode || 'original',
      price_mode: task.price_mode || 'same',
      price_adjust_pct: task.price_adjust_pct ?? 0,
      default_stock: task.default_stock ?? 999,
      target_brand: task.target_brand || '',
      follow_price_change: !!task.follow_price_change,
      follow_status_change: !!task.follow_status_change,
      category_strategy: task.category_strategy || 'use_local_map',
    })
  }

  const handleSubmitEdit = async (values) => {
    if (!editTask) return
    setEditSubmitting(true)
    try {
      // price_adjust_pct 仅 adjust_pct 模式下传; same 模式保持原值无所谓但语义干净
      const payload = { ...values }
      if (payload.price_mode === 'same') {
        payload.price_adjust_pct = 0
      }
      await cloneApi.updateTask(editTask.id, payload)
      message.success('已保存')
      setEditTask(null)
      editForm.resetFields()
      loadTasks()
    } catch (e) {
      message.error(e.message || '保存失败')
    } finally {
      setEditSubmitting(false)
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

  // 11.2: 第一步 — 调 scan-preview 拿候选清单, 弹勾选 Modal
  // 进度可视化: 先弹 Spin Modal, 后端返回后关闭再展示结果
  const handleScanNow = async (task) => {
    setScanningId(task.id)
    const progressModal = Modal.info({
      title: '正在扫描被克隆店铺...',
      icon: null,
      width: 460,
      okButtonProps: { style: { display: 'none' } },
      closable: false,
      maskClosable: false,
      content: (
        <div style={{ textAlign: 'center', padding: '24px 0' }}>
          <Spin size="large" />
          <div style={{ marginTop: 16, color: '#595959', lineHeight: 1.7 }}>
            首次扫描需 <strong>~30 秒</strong>拉取 B 店全部商品<br />
            <span style={{ color: '#1677ff' }}>15 分钟内</span>重复操作直接用本地缓存秒回
          </div>
        </div>
      ),
    })
    try {
      const r = await cloneApi.scanPreview(task.id)
      progressModal.destroy()
      const d = r.data
      const candidates = d.candidates || []
      const stats = {
        found: d.found || 0,
        skip_pending: d.skip_pending || 0,
        skip_a_shop_sku_exists: d.skip_a_shop_sku_exists || 0,
        skip_published: d.skip_published || 0,
        skip_rejected: d.skip_rejected || 0,
        skip_category_missing: d.skip_category_missing || 0,
        duration_ms: d.duration_ms || 0,
        from_cache: !!d.from_cache,
        cache_age_seconds: d.cache_age_seconds || 0,
      }
      if (candidates.length === 0) {
        // 没新候选, 直接显示统计
        Modal.info({
          title: '扫描完成 — 无新候选',
          width: 460,
          content: (
            <div>
              <p>
                共扫描 B 店商品: <strong>{stats.found}</strong> 件
                {stats.from_cache && (
                  <Tag color="cyan" style={{ marginLeft: 8 }}>
                    用 {Math.floor(stats.cache_age_seconds / 60)} 分钟前缓存
                  </Tag>
                )}
              </p>
              <div style={{ background: '#fafafa', padding: 8, marginTop: 8, fontSize: 13 }}>
                <div style={{ marginBottom: 4, color: '#666' }}>全部跳过原因:</div>
                <p style={{ margin: '2px 0' }}>· 已在审核队列: {stats.skip_pending}</p>
                <p style={{ margin: '2px 0' }}>· A 店已有同 SKU: {stats.skip_a_shop_sku_exists}</p>
                <p style={{ margin: '2px 0' }}>· 已发布到 A 店: {stats.skip_published}</p>
                <p style={{ margin: '2px 0' }}>· 之前被拒绝: {stats.skip_rejected}</p>
                <p style={{ margin: '2px 0' }}>· 类目映射缺失: {stats.skip_category_missing}</p>
              </div>
              <p style={{ marginTop: 8, color: '#999', fontSize: 12 }}>耗时 {stats.duration_ms} ms</p>
            </div>
          ),
        })
        return
      }
      // 有新候选, 弹预览 Modal — 默认勾"非冲突"项, 冲突项默认不勾让用户复核
      const defaultSelected = new Set(
        candidates.filter(c => !c.suffix_collision).map(c => c.source_sku_id),
      )
      // 本地 SKU 默认 = source_sku_id, 老板"本地编码默认一样"
      const defaultLocalSkus = {}
      candidates.forEach(c => { defaultLocalSkus[c.source_sku_id] = c.source_sku_id })
      setPreviewState({
        open: true, task, candidates, stats,
        selectedSkus: defaultSelected,
        localSkus: defaultLocalSkus,
        confirming: false,
      })
    } catch (e) {
      progressModal.destroy()
      message.error(e.message || '扫描预览失败')
    } finally {
      setScanningId(null)
    }
  }

  // 11.2: 第二步 — 用户在 Modal 勾选后点"开始克隆 X 件", 调 scan-now(selected_skus)
  const handleConfirmClone = async () => {
    const { task, selectedSkus, localSkus, candidates } = previewState
    if (selectedSkus.size === 0) {
      message.warning('请至少勾选 1 件')
      return
    }
    // 校验本地 SKU 不空 + 本批次内不重复
    const skuValues = []
    for (const id of selectedSkus) {
      const v = (localSkus[id] || '').trim()
      if (!v) {
        const c = candidates.find(x => x.source_sku_id === id)
        message.error(`商品「${(c?.title_ru || '').slice(0, 30)}」的本地 SKU 不能为空`)
        return
      }
      skuValues.push(v)
    }
    const dup = skuValues.find((v, i) => skuValues.indexOf(v) !== i)
    if (dup) {
      message.error(`本批次本地 SKU 重复: ${dup}`)
      return
    }
    setPreviewState(s => ({ ...s, confirming: true }))
    try {
      // 仅传"被改过的"映射给后端 (默认值跟 source_sku_id 同的省略)
      const overrides = {}
      for (const id of selectedSkus) {
        const v = (localSkus[id] || '').trim()
        if (v && v !== id) overrides[id] = v
      }
      const r = await cloneApi.scanNow(
        task.id, Array.from(selectedSkus),
        Object.keys(overrides).length > 0 ? overrides : null,
      )
      const d = r.data
      setPreviewState({
        open: false, task: null, candidates: [], stats: {},
        selectedSkus: new Set(), localSkus: {}, confirming: false,
      })
      Modal.success({
        title: `已立项 ${d.new || 0} 件待审核`,
        width: 420,
        content: (
          <div>
            <p>新增待审核: <strong style={{ color: '#52c41a' }}>{d.new || 0}</strong> 件</p>
            {d.ai_rewrite_total > 0 && (
              <p>AI 改写: {d.ai_rewrite_total} 条 / 失败 {d.ai_rewrite_failed}</p>
            )}
            <p style={{ marginTop: 8, color: '#999', fontSize: 12 }}>耗时 {d.duration_ms} ms</p>
            <p style={{ marginTop: 8, fontSize: 13 }}>
              请到「待审核」页面点「发布」, 1 分钟内自动上架到平台
            </p>
          </div>
        ),
      })
      loadTasks()
    } catch (e) {
      message.error(e.message || '立项失败')
      setPreviewState(s => ({ ...s, confirming: false }))
    }
  }

  const togglePreviewSku = (sku) => {
    setPreviewState(s => {
      const sel = new Set(s.selectedSkus)
      if (sel.has(sku)) sel.delete(sku)
      else sel.add(sku)
      return { ...s, selectedSkus: sel }
    })
  }
  const updateLocalSku = (sku, value) => {
    setPreviewState(s => ({
      ...s,
      localSkus: { ...s.localSkus, [sku]: value },
    }))
  }
  const toggleAllPreview = () => {
    setPreviewState(s => {
      if (s.selectedSkus.size === s.candidates.length) {
        return { ...s, selectedSkus: new Set() }
      }
      return { ...s, selectedSkus: new Set(s.candidates.map(c => c.source_sku_id)) }
    })
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

  const handleToggleFollowStatus = async (task, value) => {
    try {
      await cloneApi.updateTask(task.id, { follow_status_change: value })
      message.success(value
        ? '已开启跟上下架（B 下/上 → A 同步, status_sync beat 处理）'
        : '已关闭跟上下架')
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
      title: 'A 店 ← B 店', width: 250,
      render: (_, t) => (
        <div style={{ lineHeight: 1.7 }}>
          <div style={{ fontWeight: 500 }}>{renderShop(t.target_shop)}</div>
          <div style={{
            fontSize: 11, color: '#999', display: 'flex',
            alignItems: 'center', gap: 4, marginTop: 2,
          }}>
            <ArrowLeftOutlined style={{ fontSize: 11, color: '#bfbfbf' }} />
            {renderShop(t.source_shop)}
          </div>
        </div>
      ),
    },
    {
      title: '状态', dataIndex: 'is_active', width: 80, align: 'center',
      render: (v) => v
        ? <Badge status="success" text={<span style={{ fontSize: 13 }}>启用</span>} />
        : <Badge status="default" text={<span style={{ fontSize: 13, color: '#999' }}>停用</span>} />,
    },
    {
      title: '配置', width: 240,
      render: (_, t) => (
        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          <Space size={4} wrap>
            <Tooltip title={t.title_mode === 'ai_rewrite' ? '标题：AI 改写' : '标题：保留原文'}>
              <Tag color={t.title_mode === 'ai_rewrite' ? 'blue' : 'default'} style={{ margin: 0 }}>
                标题{t.title_mode === 'ai_rewrite' ? 'AI' : '原'}
              </Tag>
            </Tooltip>
            <Tooltip title={t.desc_mode === 'ai_rewrite' ? '描述：AI 改写' : '描述：保留原文'}>
              <Tag color={t.desc_mode === 'ai_rewrite' ? 'blue' : 'default'} style={{ margin: 0 }}>
                描述{t.desc_mode === 'ai_rewrite' ? 'AI' : '原'}
              </Tag>
            </Tooltip>
            <Tooltip title={t.price_mode === 'same' ? '价格：同 B 店' : `价格：B 店 × (1${t.price_adjust_pct >= 0 ? '+' : ''}${t.price_adjust_pct}%)`}>
              <Tag color={t.price_mode === 'same' ? 'default' : 'orange'} style={{ margin: 0 }}>
                {t.price_mode === 'same' ? '同价' : `${t.price_adjust_pct >= 0 ? '+' : ''}${t.price_adjust_pct}%`}
              </Tag>
            </Tooltip>
          </Space>
          <Space size={10} style={{ fontSize: 12 }}>
            <Tooltip title={t.follow_price_change
              ? 'B 改价 → A 自动跟改 (不走审核). 点击关闭'
              : '开启后, B 改价 → A 自动跟改 (不走审核)'}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <Switch size="small"
                  checked={!!t.follow_price_change}
                  onChange={(v) => handleToggleFollowPrice(t, v)} />
                <span style={{ color: t.follow_price_change ? '#1677ff' : '#8c8c8c' }}>跟价</span>
              </span>
            </Tooltip>
            <Tooltip title={t.follow_status_change
              ? 'B 上下架 → A 自动跟. 当前 status_sync beat 内核占位 (等 Ozon API 端点)'
              : '开启后, B 下架→A 下架, B 重上→A 已克隆过的同步上'}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <Switch size="small"
                  checked={!!t.follow_status_change}
                  onChange={(v) => handleToggleFollowStatus(t, v)} />
                <span style={{ color: t.follow_status_change ? '#1677ff' : '#8c8c8c' }}>跟上下架</span>
              </span>
            </Tooltip>
          </Space>
        </Space>
      ),
    },
    {
      title: '上次扫描', width: 160,
      render: (_, t) => (
        <div style={{ lineHeight: 1.5 }}>
          <Tooltip title={t.last_check_at ? new Date(t.last_check_at).toLocaleString('zh-CN', { hour12: false }) : '从未扫描'}>
            <Space size={4}>
              <ClockCircleOutlined style={{ fontSize: 11, color: '#bfbfbf' }} />
              <Text type="secondary" style={{ fontSize: 12 }}>
                {relativeTime(t.last_check_at)}
              </Text>
            </Space>
          </Tooltip>
          {t.last_check_at && (
            <div style={{ fontSize: 11, marginTop: 2 }}>
              <Text type="success">新 {t.last_publish_count || 0}</Text>
              <Text type="secondary"> · 跳 {t.last_skip_count || 0}</Text>
            </div>
          )}
        </div>
      ),
    },
    {
      title: '待审 / 已发', width: 130, align: 'center',
      render: (_, t) => {
        const pending = t.pending_count || 0
        const published = t.published_count || 0
        return (
          <Space size={6}>
            <Tooltip title="点查看待审记录">
              <span style={{
                display: 'inline-flex', alignItems: 'center',
                cursor: 'pointer', gap: 4,
              }} onClick={() => navigate(`/clone/pending?task_id=${t.id}`)}>
                <span style={{
                  fontSize: 16, fontWeight: 600,
                  color: pending > 0 ? '#fa8c16' : '#d9d9d9',
                  minWidth: 22, textAlign: 'right',
                }}>{pending}</span>
                {pending > 0 && (
                  <Badge status="processing" color="#fa8c16" style={{ marginLeft: -2 }} />
                )}
              </span>
            </Tooltip>
            <Text type="secondary" style={{ fontSize: 14 }}>/</Text>
            <Tooltip title="已发布到 A 店">
              <span style={{
                fontSize: 16, fontWeight: 600,
                color: published > 0 ? '#52c41a' : '#d9d9d9',
                minWidth: 22, textAlign: 'left',
              }}>{published}</span>
            </Tooltip>
          </Space>
        )
      },
    },
    {
      title: '操作', width: 210, fixed: 'right', align: 'center',
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
          <Tooltip title="编辑">
            <Button size="small" type="text" icon={<EditOutlined />}
              onClick={() => handleOpenEdit(t)} />
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
          loading={loading} scroll={{ x: 1100 }}
          size="middle"
          bordered
          pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 个任务` }}
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
          <Form.Item name="target_brand"
            label="A 店品牌名（克隆时自动替换 B 店原品牌 + 标题/描述去 B 店品牌名）"
            extra="留空 = 保留 B 店原品牌；填了之后, 商品属性的「品牌」字段强制覆盖, 标题/描述里的 B 店原品牌名也会被去除">
            <Input placeholder="例: Sharino / 你自己 A 店的品牌名" maxLength={100} />
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

      {/* 编辑任务 Modal — A/B 店锁定, 仅改策略字段 */}
      <Modal
        title={
          <Space>
            <EditOutlined />
            <span>编辑克隆任务</span>
            {editTask && (
              <Tag>#{editTask.id} {editTask.target_shop?.name} ← {editTask.source_shop?.name}</Tag>
            )}
          </Space>
        }
        open={!!editTask}
        onOk={() => editForm.submit()}
        onCancel={() => { setEditTask(null); editForm.resetFields() }}
        confirmLoading={editSubmitting}
        width={600}
        destroyOnClose
      >
        <Form form={editForm} layout="vertical" onFinish={handleSubmitEdit}>
          <Form.Item label="A 店 ← B 店">
            <div style={{
              padding: '4px 11px', background: '#fafafa',
              border: '1px solid #d9d9d9', borderRadius: 4, color: '#595959',
            }}>
              {editTask && (
                <Space size={6}>
                  {renderShop(editTask.target_shop)}
                  <ArrowLeftOutlined style={{ color: '#bfbfbf' }} />
                  {renderShop(editTask.source_shop)}
                </Space>
              )}
              <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
                （店铺配对锁定，无法修改）
              </Text>
            </div>
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
          <Form.Item name="target_brand"
            label="A 店品牌名（克隆时自动替换 B 店原品牌 + 标题/描述去 B 店品牌名）"
            extra="留空 = 保留 B 店原品牌；填了之后, 后续 publish 的商品品牌强制覆盖为这个值">
            <Input placeholder="例: Sharino / 你自己 A 店的品牌名" maxLength={100} />
          </Form.Item>
          <Form.Item name="follow_price_change" label="跟价（B 改价后 A 自动调价，不走审核）"
            valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="follow_status_change" label="跟上下架（B 上下架 → A 自动跟）"
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
            修改即时生效。改"价格策略"只影响后续新立项, 已发布商品不会回写改价 (除非开了「跟价」+ B 店真实改价).
          </Text>
        </Form>
      </Modal>

      {/* 11.2 扫描预览 Modal — 让用户勾选要克隆的 SKU */}
      <Modal
        title={
          <Space>
            <CheckCircleOutlined style={{ color: '#52c41a' }} />
            <span>扫描预览 — 选要克隆的 SKU</span>
            {previewState.task && (
              <Tag>#{previewState.task.id} {previewState.task.target_shop?.name} ← {previewState.task.source_shop?.name}</Tag>
            )}
          </Space>
        }
        open={previewState.open}
        width={1100}
        confirmLoading={previewState.confirming}
        okText={`开始克隆 (${previewState.selectedSkus.size} 件)`}
        okButtonProps={{ disabled: previewState.selectedSkus.size === 0 }}
        cancelText="取消"
        onOk={handleConfirmClone}
        onCancel={() => !previewState.confirming && setPreviewState({
          open: false, task: null, candidates: [], stats: {},
          selectedSkus: new Set(), localSkus: {}, confirming: false,
        })}
        maskClosable={!previewState.confirming}
        destroyOnClose
      >
        <div style={{ background: '#f5f5f5', padding: 10, marginBottom: 10, fontSize: 13, borderRadius: 4 }}>
          <Space split={<span style={{ color: '#ddd' }}>|</span>} wrap>
            <span>共扫描 <strong>{previewState.stats.found || 0}</strong> 件</span>
            <span style={{ color: '#52c41a' }}>新候选 <strong>{previewState.candidates.length}</strong></span>
            <span>已在队列 {previewState.stats.skip_pending || 0}</span>
            <span>A 店已有 {previewState.stats.skip_a_shop_sku_exists || 0}</span>
            <span>已发布 {previewState.stats.skip_published || 0}</span>
            <span>类目缺 {previewState.stats.skip_category_missing || 0}</span>
            <span style={{ color: '#999' }}>耗时 {previewState.stats.duration_ms || 0} ms</span>
            {previewState.stats.from_cache ? (
              <Tag color="cyan" style={{ marginInlineEnd: 0 }}>
                ✓ 用 {Math.floor((previewState.stats.cache_age_seconds || 0) / 60)} 分钟前缓存
              </Tag>
            ) : (
              <Tag color="orange" style={{ marginInlineEnd: 0 }}>现拉 API</Tag>
            )}
          </Space>
        </div>
        <Table
          rowKey="source_sku_id"
          dataSource={previewState.candidates}
          size="small"
          pagination={{ pageSize: 20, showSizeChanger: false, showTotal: t => `共 ${t} 件候选` }}
          scroll={{ y: 400 }}
          onRow={(c) => c.suffix_collision ? { style: { background: '#fff1f0' } } : {}}
          columns={[
            {
              title: (
                <Checkbox
                  checked={previewState.selectedSkus.size === previewState.candidates.length
                    && previewState.candidates.length > 0}
                  indeterminate={previewState.selectedSkus.size > 0
                    && previewState.selectedSkus.size < previewState.candidates.length}
                  onChange={toggleAllPreview}
                />
              ),
              width: 50, fixed: 'left',
              render: (_, c) => (
                <Checkbox
                  checked={previewState.selectedSkus.has(c.source_sku_id)}
                  onChange={() => togglePreviewSku(c.source_sku_id)}
                />
              ),
            },
            {
              title: '图', width: 70,
              render: (_, c) => c.images && c.images[0]
                ? <Image src={c.images[0]} width={50} height={50}
                    style={{ objectFit: 'cover', borderRadius: 4 }} preview={false}
                    placeholder fallback="" />
                : <Text type="secondary" style={{ fontSize: 12 }}>无图</Text>,
            },
            {
              title: 'B 店标题', dataIndex: 'title_ru', ellipsis: true,
              render: (v, c) => (
                <div>
                  <Text style={{ fontSize: 12 }}>{v || '-'}</Text>
                  {c.suffix_collision && (
                    <div style={{ fontSize: 11, color: '#cf1322', marginTop: 2 }}>
                      ⚠ A 店已有相同后缀 SKU: <Text code style={{ fontSize: 11 }}>
                        {c.collision_with_sku}
                      </Text> — 可能是同款, 请确认
                    </div>
                  )}
                </div>
              ),
            },
            {
              title: 'B 平台 SKU', dataIndex: 'source_sku_id', width: 120,
              render: v => <Text code style={{ fontSize: 11 }}>{v}</Text>,
            },
            {
              title: <span>本店 SKU <Tooltip title="发布到 A 店时用的 SKU (= Ozon 卖家编码 + 本地 product.sku); 默认跟 B 平台 SKU 一样, 可改"><span style={{ color: '#999', fontSize: 11 }}>?</span></Tooltip></span>,
              width: 150,
              render: (_, c) => (
                <Input
                  size="small"
                  value={previewState.localSkus[c.source_sku_id] ?? c.source_sku_id}
                  onChange={(e) => updateLocalSku(c.source_sku_id, e.target.value)}
                  status={c.suffix_collision ? 'warning' : ''}
                  placeholder={c.source_sku_id}
                  maxLength={50}
                  style={{ fontSize: 11 }}
                />
              ),
            },
            {
              title: 'B 价 → A 价', width: 140,
              render: (_, c) => (
                <span style={{ fontSize: 12 }}>
                  {c.price_b} → <strong>{c.price_a_proposed}</strong> ₽
                </span>
              ),
            },
            { title: '库存', dataIndex: 'stock', width: 60 },
            {
              title: '类目', width: 80,
              render: (_, c) => c.category_status === 'ok'
                ? <Tag color="success">OK</Tag>
                : <Tag color="warning">缺失</Tag>,
            },
          ]}
        />
        <div style={{ marginTop: 10, color: '#999', fontSize: 12 }}>
          <span style={{ color: '#cf1322' }}>红色行</span> = A 店已有相同后缀 SKU, 可能是同款, 默认不勾.
          本店 SKU 默认跟 B 平台 SKU 一样, 可在文本框里改 (会作 A 店发布的卖家编码).
        </div>
      </Modal>
    </div>
  )
}

export default CloneTaskList
