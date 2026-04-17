import { useState, useEffect, useCallback } from 'react'
import {
  Table, Button, Space, Modal, Form, Input, Select, Tag, Popconfirm,
  message, Typography, Empty, Switch, Tooltip,
} from 'antd'
import {
  PlusOutlined, CheckOutlined, EditOutlined, DeleteOutlined, ReloadOutlined,
  FolderOpenOutlined, StarFilled,
} from '@ant-design/icons'
import {
  listAttributeMappings,
  upsertAttributeMapping,
  confirmAttributeMapping,
  deleteAttributeMapping,
} from '@/api/mapping'
import ConfidenceBadge from './ConfidenceBadge'

const { Text } = Typography

const PLATFORM_COLORS = { wb: 'purple', ozon: 'blue', yandex: 'gold' }

const VALUE_TYPE_COLORS = {
  string: 'default',
  enum: 'geekblue',
  number: 'cyan',
  boolean: 'magenta',
}

const AttributeMappingTab = ({ localCategoryId, localCategoryName, onManageValues, aiSlot = null }) => {
  const [list, setList] = useState([])
  const [loading, setLoading] = useState(false)
  const [platformFilter, setPlatformFilter] = useState('all')

  const [editing, setEditing] = useState(null)
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    if (!localCategoryId) return
    setLoading(true)
    try {
      const params = { local_category_id: localCategoryId }
      if (platformFilter !== 'all') params.platform = platformFilter
      const res = await listAttributeMappings(params)
      setList(res.data?.items || [])
    } catch (err) {
      message.error(err.message || '加载属性映射失败')
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
    form.setFieldsValue({ platform: 'wb', value_type: 'string', is_required: 0 })
  }

  const openEdit = (row) => {
    setEditing({ mode: 'edit', target: row })
    form.setFieldsValue({
      platform: row.platform,
      local_attr_name: row.local_attr_name,
      local_attr_name_ru: row.local_attr_name_ru || '',
      platform_attr_id: row.platform_attr_id,
      platform_attr_name: row.platform_attr_name,
      is_required: row.is_required ? 1 : 0,
      value_type: row.value_type || 'string',
      platform_dict_id: row.platform_dict_id || '',
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
        await confirmAttributeMapping(editing.target.id, {
          local_attr_name: values.local_attr_name,
          local_attr_name_ru: values.local_attr_name_ru || null,
          platform_attr_id: values.platform_attr_id,
          platform_attr_name: values.platform_attr_name,
          is_required: values.is_required ? 1 : 0,
          value_type: values.value_type,
          platform_dict_id: values.platform_dict_id || null,
        })
        message.success('已修改并确认')
      } else {
        await upsertAttributeMapping({
          local_category_id: localCategoryId,
          platform: values.platform,
          local_attr_name: values.local_attr_name,
          local_attr_name_ru: values.local_attr_name_ru || null,
          platform_attr_id: values.platform_attr_id,
          platform_attr_name: values.platform_attr_name,
          is_required: values.is_required ? 1 : 0,
          value_type: values.value_type,
          platform_dict_id: values.platform_dict_id || null,
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
      await confirmAttributeMapping(row.id)
      message.success('已确认')
      load()
    } catch (err) {
      message.error(err.message || '确认失败')
    }
  }

  const handleDelete = async (row) => {
    try {
      await deleteAttributeMapping(row.id)
      message.success('已删除（同时级联删除属性值映射）')
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
      title: '平台属性',
      key: 'platform_attr',
      render: (_, row) => (
        <div>
          <Text strong>{row.platform_attr_name}</Text>
          <br />
          <Text type="secondary" style={{ fontSize: 12 }}>ID: {row.platform_attr_id}</Text>
        </div>
      ),
    },
    {
      title: '本地属性名',
      key: 'local_attr',
      render: (_, row) => {
        const hint = row.global_hint
        return (
          <div>
            <Space size={4}>
              <Text>{row.local_attr_name}</Text>
              {hint?.confirmed_count > 0 && (
                <Tooltip title={`全网 ${hint.confirmed_count} 个租户确认过此属性${hint.suggested_name_zh && hint.suggested_name_zh !== row.local_attr_name ? `，常用本地名："${hint.suggested_name_zh}"` : ''}`}>
                  <Tag color="gold" icon={<StarFilled />} style={{ fontSize: 11, padding: '0 4px', margin: 0 }}>
                    {hint.confirmed_count}
                  </Tag>
                </Tooltip>
              )}
            </Space>
            {row.local_attr_name_ru && (
              <>
                <br />
                <Text type="secondary" style={{ fontSize: 12 }}>{row.local_attr_name_ru}</Text>
              </>
            )}
          </div>
        )
      },
    },
    {
      title: '必填',
      dataIndex: 'is_required',
      width: 60,
      render: (v) => v ? <Tag color="red">必填</Tag> : <Tag>可选</Tag>,
    },
    {
      title: '类型',
      dataIndex: 'value_type',
      width: 80,
      render: (v) => <Tag color={VALUE_TYPE_COLORS[v] || 'default'}>{v || 'string'}</Tag>,
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
      width: 280,
      render: (_, row) => (
        <Space size={4}>
          {row.value_type === 'enum' && (
            <Button
              size="small"
              icon={<FolderOpenOutlined />}
              onClick={() => onManageValues?.(row)}
            >
              值映射
            </Button>
          )}
          {!row.is_confirmed && (
            <Button size="small" type="primary" icon={<CheckOutlined />} onClick={() => handleConfirm(row)}>
              确认
            </Button>
          )}
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>
            修改
          </Button>
          <Popconfirm
            title="删除此属性映射？"
            description="会级联删除该属性下所有属性值映射"
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
          <Button size="small" icon={<PlusOutlined />} onClick={openCreate}>手动添加属性</Button>
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
                  暂无属性映射。先在"品类映射"Tab 完成后，再点 <Text strong>AI 推荐属性</Text> 批量生成。
                </span>
              }
            />
          ),
        }}
      />

      <Modal
        open={!!editing}
        title={editing?.mode === 'edit' ? '修改属性映射' : '手动添加属性映射'}
        onCancel={closeEdit}
        onOk={submitEdit}
        confirmLoading={saving}
        destroyOnClose
        width={600}
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item name="platform" label="平台" rules={[{ required: true }]}>
            <Select
              disabled={editing?.mode === 'edit'}
              options={[{ value: 'wb', label: 'Wildberries' }, { value: 'ozon', label: 'Ozon' }]}
            />
          </Form.Item>
          <Form.Item name="local_attr_name" label="本地属性名（中文）" rules={[{ required: true }]}>
            <Input placeholder="如：材质" />
          </Form.Item>
          <Form.Item name="local_attr_name_ru" label="本地属性名（俄文，可选）">
            <Input placeholder="如：Материал" />
          </Form.Item>
          <Form.Item name="platform_attr_id" label="平台属性 ID" rules={[{ required: true }]}>
            <Input placeholder="如：10" />
          </Form.Item>
          <Form.Item name="platform_attr_name" label="平台属性名" rules={[{ required: true }]}>
            <Input placeholder="如：Материал" />
          </Form.Item>
          <Space size={24}>
            <Form.Item name="is_required" label="是否必填" valuePropName="checked" getValueFromEvent={(v) => (v ? 1 : 0)} getValueProps={(v) => ({ checked: !!v })}>
              <Switch checkedChildren="必填" unCheckedChildren="可选" />
            </Form.Item>
            <Form.Item name="value_type" label="值类型" rules={[{ required: true }]}>
              <Select
                style={{ width: 150 }}
                options={[
                  { value: 'string', label: 'string 文本' },
                  { value: 'enum', label: 'enum 枚举' },
                  { value: 'number', label: 'number 数值' },
                  { value: 'boolean', label: 'boolean 布尔' },
                ]}
              />
            </Form.Item>
          </Space>
          <Form.Item name="platform_dict_id" label="平台字典 ID（仅 enum 类型需要）">
            <Input placeholder="如：500" />
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

export default AttributeMappingTab
