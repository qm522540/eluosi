import { useState, useEffect, useCallback } from 'react'
import {
  Typography, Tabs, Table, Button, Modal, Form, Input, Select, Space,
  Tag, Popconfirm, message, Card, Descriptions, Badge, Tooltip,
} from 'antd'
import {
  PlusOutlined, EditOutlined, DeleteOutlined, ApiOutlined,
  CheckCircleOutlined, CloseCircleOutlined, ShopOutlined,
  ReloadOutlined, EyeInvisibleOutlined,
} from '@ant-design/icons'
import { getShops, createShop, updateShop, deleteShop, testConnection } from '@/api/shops'
import { PLATFORMS, SHOP_STATUS } from '@/utils/constants'

const { Title } = Typography

const platformOptions = [
  { value: 'wb', label: 'Wildberries' },
  { value: 'ozon', label: 'Ozon' },
  { value: 'yandex', label: 'Yandex Market' },
]

const Settings = () => {
  const [shops, setShops] = useState([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [modalVisible, setModalVisible] = useState(false)
  const [editingShop, setEditingShop] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [testingId, setTestingId] = useState(null)
  const [form] = Form.useForm()
  const [selectedPlatform, setSelectedPlatform] = useState(null)

  const fetchShops = useCallback(async (p = page) => {
    setLoading(true)
    try {
      const res = await getShops({ page: p, page_size: 20 })
      setShops(res.data.items)
      setTotal(res.data.total)
    } catch (err) {
      message.error('获取店铺列表失败')
    } finally {
      setLoading(false)
    }
  }, [page])

  useEffect(() => {
    fetchShops()
  }, [fetchShops])

  const handleAdd = () => {
    setEditingShop(null)
    setSelectedPlatform(null)
    form.resetFields()
    form.setFieldsValue({ currency: 'RUB', timezone: 'Europe/Moscow' })
    setModalVisible(true)
  }

  const handleEdit = (shop) => {
    setEditingShop(shop)
    setSelectedPlatform(shop.platform)
    form.setFieldsValue({
      name: shop.name,
      platform: shop.platform,
      platform_seller_id: shop.platform_seller_id,
      currency: shop.currency,
      timezone: shop.timezone,
    })
    setModalVisible(true)
  }

  const handleDelete = async (shopId) => {
    try {
      await deleteShop(shopId)
      message.success('店铺已删除')
      fetchShops()
    } catch (err) {
      message.error(err.message || '删除失败')
    }
  }

  const handleTest = async (shopId) => {
    setTestingId(shopId)
    try {
      const res = await testConnection(shopId)
      if (res.data.connected) {
        message.success('连接成功')
      } else {
        message.warning(res.data.detail || '连接失败')
      }
    } catch (err) {
      message.error(err.message || '连接测试失败')
    } finally {
      setTestingId(null)
    }
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSubmitting(true)

      if (editingShop) {
        const { platform, ...updateData } = values
        await updateShop(editingShop.id, updateData)
        message.success('店铺更新成功')
      } else {
        await createShop(values)
        message.success('店铺创建成功')
      }

      setModalVisible(false)
      fetchShops()
    } catch (err) {
      if (err.errorFields) return
      message.error(err.message || '操作失败')
    } finally {
      setSubmitting(false)
    }
  }

  const columns = [
    {
      title: '店铺名称',
      dataIndex: 'name',
      key: 'name',
      render: (text) => (
        <Space>
          <ShopOutlined />
          <span style={{ fontWeight: 500 }}>{text}</span>
        </Space>
      ),
    },
    {
      title: '平台',
      dataIndex: 'platform',
      key: 'platform',
      width: 150,
      render: (p) => {
        const info = PLATFORMS[p]
        return info ? <Tag color={info.color}>{info.label}</Tag> : p
      },
    },
    {
      title: '卖家ID',
      dataIndex: 'platform_seller_id',
      key: 'platform_seller_id',
      width: 140,
      render: (v) => v || <span style={{ color: '#ccc' }}>未填写</span>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 80,
      render: (s) => {
        const info = SHOP_STATUS[s]
        return info ? <Badge status={s === 'active' ? 'success' : 'default'} text={info.label} /> : s
      },
    },
    {
      title: '最后同步',
      dataIndex: 'last_sync_at',
      key: 'last_sync_at',
      width: 170,
      render: (v) => v ? new Date(v).toLocaleString('zh-CN') : <span style={{ color: '#ccc' }}>未同步</span>,
    },
    {
      title: '操作',
      key: 'action',
      width: 240,
      render: (_, record) => (
        <Space size="small">
          <Tooltip title="测试连接">
            <Button
              type="link"
              size="small"
              icon={<ApiOutlined />}
              loading={testingId === record.id}
              onClick={() => handleTest(record.id)}
            >
              测试
            </Button>
          </Tooltip>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确定删除此店铺？"
            description="删除后关联的数据将不再更新"
            onConfirm={() => handleDelete(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const renderCredentialFields = () => {
    const platform = selectedPlatform
    if (!platform) return null

    return (
      <>
        {(platform === 'wb' || platform === 'ozon') && (
          <Form.Item
            name="api_key"
            label="API Key"
            rules={editingShop ? [] : [{ required: true, message: '请输入API Key' }]}
          >
            <Input.Password
              placeholder={editingShop ? '不修改请留空' : '请输入API Key'}
              iconRender={() => <EyeInvisibleOutlined />}
            />
          </Form.Item>
        )}
        {platform === 'ozon' && (
          <Form.Item
            name="client_id"
            label="Client ID"
            rules={editingShop ? [] : [{ required: true, message: '请输入Client ID' }]}
          >
            <Input placeholder={editingShop ? '不修改请留空' : '请输入Ozon Client ID'} />
          </Form.Item>
        )}
        {(platform === 'wb' || platform === 'ozon') && (
          <Form.Item name="api_secret" label="API Secret">
            <Input.Password
              placeholder="选填"
              iconRender={() => <EyeInvisibleOutlined />}
            />
          </Form.Item>
        )}
        {platform === 'yandex' && (
          <>
            <Form.Item
              name="oauth_token"
              label="OAuth Token"
              rules={editingShop ? [] : [{ required: true, message: '请输入OAuth Token' }]}
            >
              <Input.Password
                placeholder={editingShop ? '不修改请留空' : '请输入Yandex OAuth Token'}
                iconRender={() => <EyeInvisibleOutlined />}
              />
            </Form.Item>
            <Form.Item name="oauth_refresh_token" label="Refresh Token">
              <Input.Password
                placeholder="选填"
                iconRender={() => <EyeInvisibleOutlined />}
              />
            </Form.Item>
          </>
        )}
      </>
    )
  }

  const shopManagement = (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <span style={{ color: '#666' }}>
          管理您的电商平台店铺，配置API密钥后系统将自动采集数据
        </span>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => fetchShops()}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>添加店铺</Button>
        </Space>
      </div>

      <Table
        columns={columns}
        dataSource={shops}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page,
          total,
          pageSize: 20,
          showTotal: (t) => `共 ${t} 个店铺`,
          onChange: (p) => { setPage(p); fetchShops(p) },
        }}
      />

      <Modal
        title={editingShop ? '编辑店铺' : '添加店铺'}
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => setModalVisible(false)}
        confirmLoading={submitting}
        width={520}
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="name"
            label="店铺名称"
            rules={[{ required: true, message: '请输入店铺名称' }]}
          >
            <Input placeholder="例如：WB旗舰店" />
          </Form.Item>

          <Form.Item
            name="platform"
            label="平台"
            rules={[{ required: true, message: '请选择平台' }]}
          >
            <Select
              placeholder="选择电商平台"
              options={platformOptions}
              disabled={!!editingShop}
              onChange={(v) => setSelectedPlatform(v)}
            />
          </Form.Item>

          <Form.Item name="platform_seller_id" label="卖家ID">
            <Input placeholder="平台上的卖家ID（选填）" />
          </Form.Item>

          {renderCredentialFields()}

          <div style={{ display: 'flex', gap: 16 }}>
            <Form.Item name="currency" label="货币" style={{ flex: 1 }}>
              <Select options={[
                { value: 'RUB', label: 'RUB (卢布)' },
                { value: 'USD', label: 'USD (美元)' },
                { value: 'CNY', label: 'CNY (人民币)' },
              ]} />
            </Form.Item>
            <Form.Item name="timezone" label="时区" style={{ flex: 1 }}>
              <Select options={[
                { value: 'Europe/Moscow', label: '莫斯科 (UTC+3)' },
                { value: 'Asia/Shanghai', label: '北京 (UTC+8)' },
              ]} />
            </Form.Item>
          </div>
        </Form>
      </Modal>
    </div>
  )

  const tabItems = [
    {
      key: 'shops',
      label: '店铺管理',
      children: shopManagement,
    },
    {
      key: 'profile',
      label: '个人信息',
      children: (
        <Card>
          <Typography.Text type="secondary">个人信息设置（开发中）</Typography.Text>
        </Card>
      ),
    },
    {
      key: 'notifications',
      label: '通知设置',
      children: (
        <Card>
          <Typography.Text type="secondary">通知推送配置（开发中）</Typography.Text>
        </Card>
      ),
    },
    {
      key: 'wechat',
      label: '企业微信',
      children: (
        <Card>
          <Typography.Text type="secondary">企业微信对接配置（开发中）</Typography.Text>
        </Card>
      ),
    },
  ]

  return (
    <div>
      <Title level={4} style={{ marginBottom: 24 }}>系统设置</Title>
      <Tabs items={tabItems} defaultActiveKey="shops" />
    </div>
  )
}

export default Settings
