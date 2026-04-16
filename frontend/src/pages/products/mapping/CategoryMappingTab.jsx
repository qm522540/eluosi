import { useState, useEffect, useCallback } from 'react'
import {
  Table, Button, Space, Modal, Form, Input, Select, Tag, Popconfirm,
  message, Typography, Empty,
} from 'antd'
import {
  PlusOutlined, CheckOutlined, EditOutlined, DeleteOutlined, ReloadOutlined,
} from '@ant-design/icons'
import {
  listCategoryMappings,
  upsertCategoryMapping,
  confirmCategoryMapping,
  deleteCategoryMapping,
} from '@/api/mapping'
import ConfidenceBadge from './ConfidenceBadge'

const { Text } = Typography

const PLATFORM_COLORS = { wb: 'purple', ozon: 'blue', yandex: 'gold' }

const CategoryMappingTab = ({ localCategoryId, localCategoryName, aiSlot = null }) => {
  const [list, setList] = useState([])
  const [loading, setLoading] = useState(false)
  const [platformFilter, setPlatformFilter] = useState('all')

  // upsert modal
  const [editing, setEditing] = useState(null) // { mode: 'create' | 'edit', target }
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    if (!localCategoryId) return
    setLoading(true)
    try {
      const params = { local_category_id: localCategoryId }
      if (platformFilter !== 'all') params.platform = platformFilter
      const res = await listCategoryMappings(params)
      setList(res.data?.items || [])
    } catch (err) {
      message.error(err.message || '加载品类映射失败')
    } finally {
      setLoading(false)
    }
  }, [localCategoryId, platformFilter])

  useEffect(() => {
    load()
  }, [load])

  const openCreate = () => {
    setEditing({ mode: 'create' })
    form.resetFields()
    form.setFieldsValue({ platform: 'wb' })
  }

  const openEdit = (row) => {
    setEditing({ mode: 'edit', target: row })
    form.setFieldsValue({
      platform: row.platform,
      platform_category_id: row.platform_category_id,
      platform_category_name: row.platform_category_name,
      platform_parent_path: row.platform_parent_path || '',
    })
  }

  const closeEdit = () => {
    setEditing(null)
    form.resetFields()
  }

  const submitEdit = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      if (editing.mode === 'edit' && editing.target) {
        // 确认接口支持同时修改，一次搞定
        await confirmCategoryMapping(editing.target.id, {
          platform_category_id: values.platform_category_id,
          platform_category_name: values.platform_category_name,
          platform_parent_path: values.platform_parent_path || null,
        })
        message.success('已修改并确认')
      } else {
        await upsertCategoryMapping({
          local_category_id: localCategoryId,
          platform: values.platform,
          platform_category_id: values.platform_category_id,
          platform_category_name: values.platform_category_name,
          platform_parent_path: values.platform_parent_path || null,
        })
        message.success('映射已保存')
      }
      closeEdit()
      load()
    } catch (err) {
      if (err?.errorFields) return
      message.error(err.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleConfirm = async (row) => {
    try {
      await confirmCategoryMapping(row.id)
      message.success('已确认')
      load()
    } catch (err) {
      message.error(err.message || '确认失败')
    }
  }

  const handleDelete = async (row) => {
    try {
      await deleteCategoryMapping(row.id)
      message.success('已删除')
      load()
    } catch (err) {
      message.error(err.message || '删除失败')
    }
  }

  const columns = [
    {
      title: '平台',
      dataIndex: 'platform',
      width: 80,
      render: (p) => <Tag color={PLATFORM_COLORS[p] || 'default'}>{p.toUpperCase()}</Tag>,
    },
    {
      title: '平台分类',
      key: 'platform_category',
      render: (_, row) => (
        <div>
          <Text strong>{row.platform_category_name}</Text>
          <br />
          <Text type="secondary" style={{ fontSize: 12 }}>
            ID: {row.platform_category_id}
          </Text>
        </div>
      ),
    },
    {
      title: '面包屑',
      dataIndex: 'platform_parent_path',
      ellipsis: true,
      render: (v) => v || <Text type="secondary">—</Text>,
    },
    {
      title: '状态',
      key: 'status',
      width: 180,
      render: (_, row) => (
        <ConfidenceBadge
          aiSuggested={row.ai_suggested}
          confidence={row.ai_confidence}
          confirmed={row.is_confirmed}
        />
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 220,
      render: (_, row) => (
        <Space size={4}>
          {!row.is_confirmed && (
            <Button size="small" type="primary" icon={<CheckOutlined />} onClick={() => handleConfirm(row)}>
              确认
            </Button>
          )}
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>
            修改
          </Button>
          <Popconfirm
            title="删除此映射？"
            okText="删除"
            okButtonProps={{ danger: true }}
            cancelText="取消"
            onConfirm={() => handleDelete(row)}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 12, justifyContent: 'space-between', width: '100%' }}>
        <Space>
          <Text type="secondary">
            当前分类：<Text strong>{localCategoryName}</Text>
          </Text>
          <Select
            size="small"
            value={platformFilter}
            onChange={setPlatformFilter}
            style={{ width: 110 }}
            options={[
              { value: 'all', label: '全部平台' },
              { value: 'wb', label: 'WB' },
              { value: 'ozon', label: 'Ozon' },
            ]}
          />
          <Button size="small" icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        </Space>
        <Space>
          {aiSlot}
          <Button size="small" icon={<PlusOutlined />} onClick={openCreate}>手动添加映射</Button>
        </Space>
      </Space>

      <Table
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={list}
        columns={columns}
        pagination={false}
        locale={{
          emptyText: (
            <Empty
              description={
                <span>
                  暂无映射。可点 <Text strong>AI 推荐映射</Text> 让 AI 自动生成，或 <Text strong>手动添加</Text>。
                </span>
              }
            />
          ),
        }}
      />

      <Modal
        open={!!editing}
        title={editing?.mode === 'edit' ? '修改品类映射' : '手动添加品类映射'}
        onCancel={closeEdit}
        onOk={submitEdit}
        confirmLoading={saving}
        destroyOnClose
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item name="platform" label="平台" rules={[{ required: true }]}>
            <Select
              disabled={editing?.mode === 'edit'}
              options={[
                { value: 'wb', label: 'Wildberries' },
                { value: 'ozon', label: 'Ozon' },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="platform_category_id"
            label="平台分类 ID"
            rules={[{ required: true, message: '平台分类 ID 必填' }]}
          >
            <Input placeholder="如：123（WB subjectID / Ozon type_id）" />
          </Form.Item>
          <Form.Item
            name="platform_category_name"
            label="平台分类名"
            rules={[{ required: true, message: '平台分类名必填' }]}
          >
            <Input placeholder="如：Ожерелья" />
          </Form.Item>
          <Form.Item name="platform_parent_path" label="面包屑（可选）">
            <Input placeholder="如：Украшения > Ожерелья" />
          </Form.Item>
          {editing?.mode === 'edit' && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              注：修改保存后会自动置为"已确认"状态
            </Text>
          )}
        </Form>
      </Modal>
    </div>
  )
}

export default CategoryMappingTab
