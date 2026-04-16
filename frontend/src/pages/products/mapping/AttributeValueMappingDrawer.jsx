import { useState, useEffect, useCallback } from 'react'
import {
  Drawer, Table, Button, Space, Modal, Form, Input, Popconfirm, Tag,
  message, Typography, Empty, Tooltip,
} from 'antd'
import {
  PlusOutlined, CheckOutlined, EditOutlined, DeleteOutlined, ReloadOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import {
  listAttributeValueMappings,
  upsertAttributeValueMapping,
  confirmAttributeValueMapping,
  deleteAttributeValueMapping,
} from '@/api/mapping'
import ConfidenceBadge from './ConfidenceBadge'

const { Text } = Typography

const PLATFORM_COLORS = { wb: 'purple', ozon: 'blue', yandex: 'gold' }

const AttributeValueMappingDrawer = ({ open, attributeMapping, onClose }) => {
  const [list, setList] = useState([])
  const [loading, setLoading] = useState(false)

  const [editing, setEditing] = useState(null)
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)

  const attrId = attributeMapping?.id

  const load = useCallback(async () => {
    if (!attrId) return
    setLoading(true)
    try {
      const res = await listAttributeValueMappings(attrId)
      setList(res.data?.items || [])
    } catch (err) {
      message.error(err.message || '加载属性值映射失败')
    } finally {
      setLoading(false)
    }
  }, [attrId])

  useEffect(() => {
    if (open) load()
    else setList([])
  }, [open, load])

  const openCreate = () => {
    setEditing({ mode: 'create' })
    form.resetFields()
  }

  const openEdit = (row) => {
    setEditing({ mode: 'edit', target: row })
    form.setFieldsValue({
      local_value: row.local_value,
      local_value_ru: row.local_value_ru || '',
      platform_value: row.platform_value,
      platform_value_id: row.platform_value_id || '',
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
        await confirmAttributeValueMapping(editing.target.id, {
          local_value: values.local_value,
          local_value_ru: values.local_value_ru || null,
          platform_value: values.platform_value,
          platform_value_id: values.platform_value_id || null,
        })
        message.success('已修改并确认')
      } else {
        await upsertAttributeValueMapping({
          attribute_mapping_id: attrId,
          local_value: values.local_value,
          local_value_ru: values.local_value_ru || null,
          platform_value: values.platform_value,
          platform_value_id: values.platform_value_id || null,
        })
        message.success('值映射已保存')
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
      await confirmAttributeValueMapping(row.id)
      message.success('已确认')
      load()
    } catch (err) {
      message.error(err.message || '确认失败')
    }
  }

  const handleDelete = async (row) => {
    try {
      await deleteAttributeValueMapping(row.id)
      message.success('已删除')
      load()
    } catch (err) {
      message.error(err.message || '删除失败')
    }
  }

  const columns = [
    {
      title: '本地值',
      key: 'local',
      render: (_, row) => (
        <div>
          <Text strong>{row.local_value}</Text>
          {row.local_value_ru && (
            <>
              <br />
              <Text type="secondary" style={{ fontSize: 12 }}>{row.local_value_ru}</Text>
            </>
          )}
        </div>
      ),
    },
    {
      title: '平台值',
      key: 'platform',
      render: (_, row) => (
        <div>
          <Text>{row.platform_value}</Text>
          {row.platform_value_id && (
            <>
              <br />
              <Text type="secondary" style={{ fontSize: 12 }}>ID: {row.platform_value_id}</Text>
            </>
          )}
        </div>
      ),
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
      width: 200,
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
            title="删除此值映射？"
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

  const title = attributeMapping ? (
    <Space size="small" wrap>
      <span>属性值映射</span>
      <Tag color={PLATFORM_COLORS[attributeMapping.platform] || 'default'}>
        {(attributeMapping.platform || '').toUpperCase()}
      </Tag>
      <Text strong>{attributeMapping.local_attr_name}</Text>
      <Text type="secondary">↔ {attributeMapping.platform_attr_name}</Text>
    </Space>
  ) : '属性值映射'

  return (
    <Drawer
      open={open}
      title={title}
      width={720}
      onClose={onClose}
      destroyOnClose
      extra={
        <Space>
          <Tooltip title="后端框架已就绪，等平台枚举值 API 接入后启用">
            <Button size="small" disabled icon={<ThunderboltOutlined />}>
              AI 推荐（暂未启用）
            </Button>
          </Tooltip>
          <Button size="small" icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          <Button size="small" type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            手动添加
          </Button>
        </Space>
      }
    >
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
                  暂无值映射。点 <Text strong>手动添加</Text> 建立枚举值对应关系。
                  <br />
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    （后端 AI 推荐框架就绪，等平台枚举值接入后自动填充）
                  </Text>
                </span>
              }
            />
          ),
        }}
      />

      <Modal
        open={!!editing}
        title={editing?.mode === 'edit' ? '修改值映射' : '手动添加值映射'}
        onCancel={closeEdit}
        onOk={submitEdit}
        confirmLoading={saving}
        destroyOnClose
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item name="local_value" label="本地值（中文）" rules={[{ required: true }]}>
            <Input placeholder="如：925银" />
          </Form.Item>
          <Form.Item name="local_value_ru" label="本地值（俄文，可选）">
            <Input placeholder="如：Серебро 925" />
          </Form.Item>
          <Form.Item name="platform_value" label="平台值" rules={[{ required: true }]}>
            <Input placeholder="如：Серебро 925 пробы" />
          </Form.Item>
          <Form.Item name="platform_value_id" label="平台字典值 ID（可选）">
            <Input placeholder="如：11" />
          </Form.Item>
          {editing?.mode === 'edit' && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              注：修改保存后会自动置为"已确认"状态
            </Text>
          )}
        </Form>
      </Modal>
    </Drawer>
  )
}

export default AttributeValueMappingDrawer
