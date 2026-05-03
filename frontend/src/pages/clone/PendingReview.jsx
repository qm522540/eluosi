import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Card, Tabs, List, Button, Space, Tag, Image, Modal, Input, message,
  Empty, Typography, Select, Checkbox, Tooltip,
} from 'antd'
import {
  CheckOutlined, EditOutlined,
  WarningOutlined, DeleteOutlined,
} from '@ant-design/icons'
import * as cloneApi from '@/api/clone'

const { Title, Text, Paragraph } = Typography

const PendingReview = () => {
  const [searchParams] = useSearchParams()
  const [taskId, setTaskId] = useState(searchParams.get('task_id') || null)
  const [status, setStatus] = useState('pending')
  const [items, setItems] = useState([])
  const [tasks, setTasks] = useState([])
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState(new Set())
  const [editTarget, setEditTarget] = useState(null)
  const [editForm, setEditForm] = useState({})

  const load = async () => {
    setLoading(true)
    try {
      const params = { status, page: 1, size: 50 }
      if (taskId) params.task_id = taskId
      const r = await cloneApi.listPending(params)
      setItems(r.data?.items || [])
    } catch (e) {
      message.error(e.message || '加载待审核失败')
    } finally {
      setLoading(false)
    }
  }

  const loadTasks = async () => {
    try {
      const r = await cloneApi.listTasks({ size: 100 })
      setTasks(r.data?.items || [])
    } catch (_e) {
      // 静默 — 任务过滤下拉不可用不阻塞主功能
    }
  }

  useEffect(() => { loadTasks() }, [])
  useEffect(() => { load(); setSelected(new Set()) }, [taskId, status])

  const handlePublish = async (id) => {
    try {
      await cloneApi.publishPending(id)
      message.success('已加入上架队列, 1 分钟内自动上架到平台')
      load()
    } catch (e) {
      message.error(e.message || '发布失败')
    }
  }

  const handleBatchPublish = async () => {
    if (selected.size === 0) return
    try {
      const r = await cloneApi.batchPublish(Array.from(selected))
      message.success(`批量发布: 成功 ${r.data.success} / 失败 ${r.data.failed}, 1 分钟内自动上架`)
      setSelected(new Set())
      load()
    } catch (e) {
      message.error(e.message || '批量发布失败')
    }
  }

  const handleBatchDelete = async () => {
    if (selected.size === 0) return
    Modal.confirm({
      title: `确认彻底删除 ${selected.size} 条？(不可恢复)`,
      content: (
        <div>
          <p style={{ color: '#cf1322' }}>
            <strong>物理删除</strong> 3 张表 (pending + 草稿 listing + 草稿 product),
            不可恢复.
          </p>
          <p>删后下次扫描遇到同 SKU 会<strong>重新作为新候选立项</strong> (重新采).</p>
          <p style={{ color: '#999', fontSize: 12 }}>
            限制: 仅 pending / 已拒绝 / 上架失败 状态可删. 已批准/已发布的不允许.
          </p>
        </div>
      ),
      okText: '确认彻底删除',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const r = await cloneApi.batchDeletePending(Array.from(selected))
          const d = r.data
          message.success(
            `彻底删除: ${d.deleted_pending} 条 pending` +
            (d.skipped_count > 0 ? ` (跳过 ${d.skipped_count} 条状态不允许)` : '')
          )
          setSelected(new Set())
          load()
        } catch (e) {
          message.error(e.message || '彻底删除失败')
        }
      },
    })
  }

  const openEdit = (item) => {
    setEditTarget(item)
    setEditForm({
      title_ru: item.proposed?.title_ru || '',
      description_ru: item.proposed?.description_ru || '',
      price_rub: item.proposed?.price_rub || 0,
      stock: item.proposed?.stock || 0,
    })
  }

  const submitEdit = async () => {
    try {
      await cloneApi.updatePendingPayload(editTarget.id, editForm)
      message.success('已保存')
      setEditTarget(null)
      load()
    } catch (e) {
      message.error(e.message || '保存失败')
    }
  }

  const toggleSelect = (id) => {
    const newSel = new Set(selected)
    if (newSel.has(id)) newSel.delete(id)
    else newSel.add(id)
    setSelected(newSel)
  }

  const toggleSelectAll = () => {
    if (selected.size === items.length) setSelected(new Set())
    else setSelected(new Set(items.map(i => i.id)))
  }

  const renderItem = (item) => {
    const src = item.source || {}
    const prop = item.proposed || {}
    const aiFailed = prop._ai_rewrite_failed_title || prop._ai_rewrite_failed_desc
    const catMissing = item.category_mapping_status === 'missing'

    return (
      <List.Item
        style={{ padding: 16, background: catMissing ? '#fff2e8' : 'inherit' }}
        actions={status === 'pending' ? [
          <Button key="publish" type="primary" icon={<CheckOutlined />} size="small"
            onClick={() => handlePublish(item.id)}>发布</Button>,
          <Button key="edit" icon={<EditOutlined />} size="small"
            onClick={() => openEdit(item)}>编辑</Button>,
        ] : []}
      >
        {status === 'pending' && (
          <Checkbox
            checked={selected.has(item.id)}
            onChange={() => toggleSelect(item.id)}
            style={{ marginRight: 12 }}
          />
        )}
        <div style={{ display: 'flex', gap: 16, width: '100%' }}>
          {/* 左：B 店原商品 */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>B 店原商品 ({src.platform} / {src.sku_id})</Text>
            {src.images?.[0] && (
              <Image src={src.images[0]} width={80} height={80}
                style={{ objectFit: 'cover', borderRadius: 4, marginTop: 4 }}
                placeholder fallback="" />
            )}
            <div style={{ fontSize: 13, marginTop: 4 }}>{src.title_ru}</div>
            <Tag color="default" style={{ marginTop: 4 }}>
              {src.price_rub} ₽ / 库存 {src.stock}
            </Tag>
          </div>

          {/* 右：A 店改写后 */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <Space>
              <Text type="secondary" style={{ fontSize: 12 }}>A 店克隆后</Text>
              {aiFailed && (
                <Tooltip title="AI 改写失败已 fallback 到原文，可手动改">
                  <WarningOutlined style={{ color: '#fa8c16' }} />
                </Tooltip>
              )}
              {catMissing && <Tag color="warning">类目映射缺失</Tag>}
            </Space>
            {prop.images_oss?.[0] && (
              <Image src={prop.images_oss[0]} width={80} height={80}
                style={{ objectFit: 'cover', borderRadius: 4, marginTop: 4 }}
                placeholder fallback="" />
            )}
            <div style={{ fontSize: 13, marginTop: 4 }}>{prop.title_ru}</div>
            <Tag color="blue" style={{ marginTop: 4 }}>
              {prop.price_rub} ₽ / 库存 {prop.stock}
            </Tag>
            {item.publish_error_msg && (
              <Paragraph type="danger" style={{ fontSize: 12, marginTop: 4 }}>
                上架失败: {item.publish_error_msg}
              </Paragraph>
            )}
          </div>
        </div>
      </List.Item>
    )
  }

  return (
    <div style={{ padding: 16 }}>
      <Card
        title={<Title level={4} style={{ margin: 0 }}>待审核商品</Title>}
        extra={
          <Space>
            <Select value={taskId} placeholder="按任务过滤" allowClear
              style={{ width: 240 }} onChange={setTaskId}
              options={[
                { value: null, label: '全部任务' },
                ...tasks.map(t => ({
                  value: t.id,
                  label: `#${t.id} ${t.target_shop?.name} ← ${t.source_shop?.name}`,
                })),
              ]} />
          </Space>
        }
      >
        <Tabs activeKey={status} onChange={setStatus}
          items={[
            { key: 'pending', label: '待审核' },
            { key: 'published', label: '已发布' },
            { key: 'failed', label: '上架失败' },
          ]} />

        {(status === 'pending' || status === 'failed') && items.length > 0 && (
          <Space style={{ marginBottom: 12 }} wrap>
            <Checkbox
              checked={selected.size === items.length && items.length > 0}
              indeterminate={selected.size > 0 && selected.size < items.length}
              onChange={toggleSelectAll}>全选</Checkbox>
            {status === 'pending' && (
              <Button type="primary" icon={<CheckOutlined />}
                disabled={selected.size === 0} onClick={handleBatchPublish}>
                批量发布 ({selected.size})
              </Button>
            )}
            <Button danger icon={<DeleteOutlined />}
              disabled={selected.size === 0} onClick={handleBatchDelete}>
              彻底删除 ({selected.size})
            </Button>
            <span style={{ color: '#999', fontSize: 12 }}>
              不发也不删 = 留在待审核, 下次扫描会自动跳过 (永不重抓);
              彻底删除 = 物理删, 下次扫描重新采
            </span>
          </Space>
        )}

        {items.length === 0 && !loading ? (
          <Empty description="无待审核记录" />
        ) : (
          <List
            loading={loading}
            dataSource={items}
            renderItem={renderItem}
            pagination={{ pageSize: 20 }}
          />
        )}
      </Card>

      <Modal
        title="编辑商品信息"
        open={!!editTarget}
        onOk={submitEdit}
        onCancel={() => setEditTarget(null)}
        width={600}
      >
        {editTarget && (
          <Space direction="vertical" style={{ width: '100%' }}>
            <div>
              <Text type="secondary">标题（RU）</Text>
              <Input.TextArea rows={2}
                value={editForm.title_ru}
                onChange={e => setEditForm(s => ({ ...s, title_ru: e.target.value }))} />
            </div>
            <div>
              <Text type="secondary">描述（RU）</Text>
              <Input.TextArea rows={4}
                value={editForm.description_ru}
                onChange={e => setEditForm(s => ({ ...s, description_ru: e.target.value }))} />
            </div>
            <Space>
              <div>
                <Text type="secondary">价格 ₽</Text>
                <Input type="number" value={editForm.price_rub}
                  onChange={e => setEditForm(s => ({ ...s, price_rub: Number(e.target.value) }))} />
              </div>
              <div>
                <Text type="secondary">库存</Text>
                <Input type="number" value={editForm.stock}
                  onChange={e => setEditForm(s => ({ ...s, stock: Number(e.target.value) }))} />
              </div>
            </Space>
          </Space>
        )}
      </Modal>
    </div>
  )
}

export default PendingReview
