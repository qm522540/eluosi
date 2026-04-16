import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Typography, Card, Table, Button, Tag, Space, Row, Col,
  Input, Select, InputNumber, Modal, Form, Tooltip, Empty,
  Badge, message, Popconfirm, Alert, Spin, Drawer,
} from 'antd'
import {
  SyncOutlined, PlusOutlined, EditOutlined, DeleteOutlined,
  RobotOutlined, SendOutlined, ShopOutlined,
} from '@ant-design/icons'
import {
  getProducts, syncProducts, checkSyncNeeded,
  updateProductMargin, deleteProduct, generateDescription,
  spreadProducts, getSpreadRecords, updateProduct,
} from '@/api/products'
import { getShops } from '@/api/shops'
import { useAuthStore } from '@/stores/authStore'

const { Text } = Typography
const { Option } = Select

const PLATFORM_COLOR = {
  wb: { bg: '#FBEAF0', color: '#993556', label: 'WB' },
  ozon: { bg: '#E6F1FB', color: '#185FA5', label: 'Ozon' },
  yandex: { bg: '#FAEEDA', color: '#633806', label: 'YM' },
}

const STATUS_MAP = {
  active: { color: 'success', label: '在售' },
  inactive: { color: 'default', label: '停售' },
  out_of_stock: { color: 'warning', label: '缺货' },
  blocked: { color: 'error', label: '封禁' },
}

const Products = () => {
  const tenant = useAuthStore(s => s.tenant)
  const tenantId = tenant?.id

  const [products, setProducts] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [lastSyncAt, setLastSyncAt] = useState(null)

  const [filters, setFilters] = useState({
    keyword: '', category: '', platform: '', shop_id: null, status: 'active',
  })
  const [shops, setShops] = useState([])
  const [page, setPage] = useState(1)
  const [pageSize] = useState(20)

  const [editingMargin, setEditingMargin] = useState({})
  const [expandedRows, setExpandedRows] = useState([])

  const [spreadModal, setSpreadModal] = useState(false)
  const [spreadItems, setSpreadItems] = useState([])
  const [spreadForm] = Form.useForm()
  const [spreading, setSpreading] = useState(false)

  const [descDrawer, setDescDrawer] = useState(false)
  const [descListing, setDescListing] = useState(null)
  const [descPlatform, setDescPlatform] = useState('ozon')
  const [descLoading, setDescLoading] = useState(false)
  const [generatedDesc, setGeneratedDesc] = useState('')

  const [selectedRowKeys, setSelectedRowKeys] = useState([])

  const fetchProducts = useCallback(async (p = 1) => {
    setLoading(true)
    setPage(p)
    try {
      const res = await getProducts({
        ...filters,
        page: p,
        page_size: pageSize,
      })
      setProducts(res.data?.items || [])
      setTotal(res.data?.total || 0)
    } catch {
      setProducts([])
    } finally {
      setLoading(false)
    }
  }, [filters, pageSize])

  useEffect(() => {
    fetchProducts(1)
  }, [fetchProducts])

  useEffect(() => {
    getShops({ page: 1, page_size: 100 }).then(res => {
      setShops(res.data?.items || [])
    }).catch(() => setShops([]))
  }, [])

  const handleSync = async (force = false) => {
    if (!filters.shop_id) {
      message.warning('请先在上方下拉框选择店铺')
      return
    }
    setSyncing(true)
    try {
      const res = await syncProducts(filters.shop_id, force)
      if (res.data?.syncing) {
        message.success('同步任务已启动，请稍后刷新')
        setTimeout(() => fetchProducts(1), 3000)
      } else {
        message.info(res.data?.message || '无需同步')
      }
    } catch (e) {
      message.error('同步失败')
    } finally {
      setSyncing(false)
    }
  }

  const handleMarginSave = async (productId, value) => {
    try {
      const margin = value ? parseFloat(value) / 100 : null
      await updateProductMargin(productId, margin)
      message.success('净毛利率已更新')
      setEditingMargin(prev => ({ ...prev, [productId]: undefined }))
      fetchProducts(page)
    } catch {
      message.error('更新失败')
    }
  }

  const handleDelete = async (productId) => {
    try {
      await deleteProduct(productId)
      message.success('商品已删除')
      fetchProducts(page)
    } catch {
      message.error('删除失败')
    }
  }

  const handleSpread = (listings) => {
    setSpreadItems(listings)
    setSpreadModal(true)
  }

  const handleSpreadSubmit = async () => {
    try {
      const values = await spreadForm.validateFields()
      setSpreading(true)
      await spreadProducts({
        src_listing_ids: spreadItems.map(l => l.id),
        dst_shop_ids: values.dst_shop_ids,
        price_mode: values.price_mode || 'original',
        ai_rewrite_title: values.ai_rewrite_title || false,
        ai_change_bg: values.ai_change_bg || false,
      })
      message.success(`铺货任务已提交，共${spreadItems.length}个商品`)
      setSpreadModal(false)
      spreadForm.resetFields()
    } catch (e) {
      if (e.errorFields) return
      message.error('铺货失败')
    } finally {
      setSpreading(false)
    }
  }

  const handleGenerateDesc = async () => {
    if (!descListing) return
    setDescLoading(true)
    try {
      const res = await generateDescription(descListing.id, descPlatform)
      setGeneratedDesc(res.data?.description || '')
    } catch {
      message.error('AI改写失败')
    } finally {
      setDescLoading(false)
    }
  }

  const marginColumn = {
    title: '净毛利率',
    dataIndex: 'net_margin',
    width: 110,
    render: (v, record) => {
      const isEditing = editingMargin[record.id] !== undefined
      if (isEditing) {
        return (
          <InputNumber
            size="small"
            min={1} max={99} step={1}
            defaultValue={v ? Math.round(v * 100) : undefined}
            addonAfter="%"
            style={{ width: 90 }}
            autoFocus
            onBlur={e => handleMarginSave(record.id, e.target.value)}
            onPressEnter={e => handleMarginSave(record.id, e.target.value)}
          />
        )
      }
      return (
        <Tooltip title="点击编辑">
          <span
            onClick={() => setEditingMargin(prev => ({ ...prev, [record.id]: true }))}
            style={{ cursor: 'pointer' }}
          >
            {v ? (
              <Tag color="green" style={{ cursor: 'pointer' }}>
                {Math.round(v * 100)}%
              </Tag>
            ) : (
              <Tag color="default" style={{ cursor: 'pointer', color: '#888' }}>
                默认
              </Tag>
            )}
          </span>
        </Tooltip>
      )
    },
  }

  const columns = [
    {
      title: '商品',
      dataIndex: 'name_ru',
      width: 220,
      render: (v, record) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {record.image_url ? (
            <img src={record.image_url} alt=""
              style={{ width: 40, height: 40, objectFit: 'cover',
                borderRadius: 6, border: '0.5px solid var(--color-border-tertiary)' }} />
          ) : (
            <div style={{ width: 40, height: 40, background: 'var(--color-background-secondary)',
              borderRadius: 6, border: '0.5px solid var(--color-border-tertiary)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 10, color: 'var(--color-text-tertiary)' }}>图</div>
          )}
          <div>
            <div style={{ fontWeight: 500, fontSize: 13 }}>
              {v || record.name_zh || record.sku}
            </div>
            <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>
              {record.sku}
            </div>
          </div>
        </div>
      ),
    },
    {
      title: '分类',
      dataIndex: 'local_category_name',
      width: 100,
      render: (v, record) => {
        if (v) {
          return <Tag color="blue" style={{ fontSize: 12 }}>{v}</Tag>
        }
        // 本地分类未关联时，降级显示平台分类名（俄文）作为参考
        const fallback = (record.listings || [])
          .map(l => l.platform_category_name)
          .find(n => n)
        return fallback ? (
          <Tooltip title="本地分类未关联，显示平台原始分类">
            <Text style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>{fallback}</Text>
          </Tooltip>
        ) : <Text style={{ color: 'var(--color-text-tertiary)' }}>-</Text>
      },
    },
    marginColumn,
    {
      title: (
        <Tooltip title="商家在平台后台设置的销售价，非买家到手价（不含平台补贴/券后/会员折扣）">
          <span>销售价 <span style={{ color: 'var(--color-text-tertiary)', fontSize: 11 }}>ⓘ</span></span>
        </Tooltip>
      ),
      width: 120,
      render: (_, record) => {
        const listings = record.listings || []
        const wbL = listings.find(l => l.platform === 'wb')
        const ozL = listings.find(l => l.platform === 'ozon')
        return (
          <div style={{ fontSize: 12 }}>
            {wbL && <div style={{ color: '#993556' }}>
              WB: ₽{Math.round(wbL.discount_price || wbL.price || 0)}
            </div>}
            {ozL && <div style={{ color: '#185FA5' }}>
              Ozon: ₽{Math.round(ozL.discount_price || ozL.price || 0)}
            </div>}
          </div>
        )
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 70,
      render: v => {
        const cfg = STATUS_MAP[v] || { color: 'default', label: v }
        return <Badge status={cfg.color} text={cfg.label} style={{ fontSize: 12 }} />
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 130,
      render: (_, record) => (
        <Space size={4}>
          <Button size="small" icon={<EditOutlined />}
            onClick={() => {}}>编辑</Button>
          <Button size="small" type="primary"
            style={{ background: '#185FA5', borderColor: '#185FA5' }}
            icon={<SendOutlined />}
            onClick={() => handleSpread(record.listings || [])}>
            铺货
          </Button>
          <Popconfirm title="确认删除？" onConfirm={() => handleDelete(record.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const expandedRowRender = (record) => {
    const subColumns = [
      {
        title: '平台',
        dataIndex: 'platform',
        width: 60,
        render: v => {
          const cfg = PLATFORM_COLOR[v] || {}
          return (
            <div style={{
              width: 22, height: 22, borderRadius: 4,
              background: cfg.bg, color: cfg.color,
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 10, fontWeight: 500,
            }}>{cfg.label}</div>
          )
        },
      },
      { title: '变体', dataIndex: 'variant_name', width: 80,
        render: v => v || '-' },
      { title: '平台编号', dataIndex: 'platform_product_id', width: 110,
        render: v => <Text style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>{v}</Text> },
      { title: '售价', dataIndex: 'price', width: 70,
        render: v => v ? `₽${Math.round(v)}` : '-' },
      { title: '折扣价', dataIndex: 'discount_price', width: 70,
        render: v => v ? `₽${Math.round(v)}` : '-' },
      { title: '评分', dataIndex: 'rating', width: 55,
        render: v => v ? v.toFixed(1) : '-' },
      {
        title: '状态', dataIndex: 'status', width: 70,
        render: v => {
          const cfg = STATUS_MAP[v] || { color: 'default', label: v }
          return <Badge status={cfg.color} text={cfg.label} style={{ fontSize: 11 }} />
        },
      },
      {
        title: '操作', key: 'action', width: 160,
        render: (_, l) => (
          <Space size={4}>
            <Button size="small"
              onClick={() => handleSpread([l])}
              disabled={l.status !== 'active'}
              style={{ fontSize: 11 }}>
              铺货
            </Button>
            <Button size="small" icon={<RobotOutlined />}
              onClick={() => { setDescListing(l); setDescDrawer(true) }}
              style={{ fontSize: 11 }}>
              AI改写
            </Button>
          </Space>
        ),
      },
    ]

    return (
      <Table
        columns={subColumns}
        dataSource={record.listings || []}
        rowKey="id"
        pagination={false}
        size="small"
        style={{ margin: '0 52px 0 52px' }}
      />
    )
  }

  return (
    <div style={{ padding: '16px' }}>
      <Card
        size="small"
        style={{ marginBottom: 12 }}
        bodyStyle={{ padding: '12px 16px' }}
      >
        <Row gutter={8} align="middle" wrap>
          <Col><Input placeholder="搜索SKU/商品名" style={{ width: 180 }}
            value={filters.keyword}
            onChange={e => setFilters(p => ({ ...p, keyword: e.target.value }))}
            onPressEnter={() => fetchProducts(1)} /></Col>
          <Col>
            <Select
              style={{ width: 220 }}
              value={filters.shop_id}
              onChange={(shopId, opt) => setFilters(p => ({
                ...p,
                shop_id: shopId ?? null,
                platform: opt?.platform || '',
              }))}
              placeholder="选择店铺（单店管理）"
              allowClear
              showSearch
              optionFilterProp="children"
            >
              {['wb', 'ozon', 'yandex'].map(plat => {
                const list = shops.filter(s => s.platform === plat)
                if (!list.length) return null
                const cfg = PLATFORM_COLOR[plat] || {}
                return (
                  <Select.OptGroup key={plat} label={cfg.label}>
                    {list.map(s => (
                      <Option key={s.id} value={s.id} platform={plat}>
                        {cfg.label} · {s.name}
                      </Option>
                    ))}
                  </Select.OptGroup>
                )
              })}
            </Select>
          </Col>
          <Col>
            <Select style={{ width: 100 }} value={filters.status}
              onChange={v => setFilters(p => ({ ...p, status: v }))}>
              <Option value="active">在售</Option>
              <Option value="">全部状态</Option>
              <Option value="out_of_stock">缺货</Option>
              <Option value="inactive">停售</Option>
            </Select>
          </Col>
          <Col>
            <Button type="primary" onClick={() => fetchProducts(1)}>查询</Button>
          </Col>
          <Col>
            <Button onClick={() => {
              setFilters({ keyword: '', category: '', platform: '', shop_id: null, status: 'active' })
              setTimeout(() => fetchProducts(1), 0)
            }}>重置</Button>
          </Col>
          <Col flex={1} />
          {lastSyncAt && (
            <Col>
              <Text style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                上次同步：{lastSyncAt}
              </Text>
            </Col>
          )}
          <Col>
            <Button icon={<SyncOutlined spin={syncing} />}
              loading={syncing} onClick={() => handleSync(true)}>
              手动同步
            </Button>
          </Col>
          <Col>
            <Button type="primary" icon={<PlusOutlined />}
              onClick={() => {}}>新增商品</Button>
          </Col>
          {selectedRowKeys.length > 0 && (
            <Col>
              <Button
                style={{ background: '#854F0B', borderColor: '#854F0B', color: '#FAC775' }}
                icon={<SendOutlined />}
                onClick={() => {
                  const selectedListings = products
                    .filter(p => selectedRowKeys.includes(p.id))
                    .flatMap(p => p.listings || [])
                    .filter(l => l.status === 'active')
                  handleSpread(selectedListings)
                }}>
                批量铺货 ({selectedRowKeys.length})
              </Button>
            </Col>
          )}
        </Row>
      </Card>

      <Card size="small" bodyStyle={{ padding: 0 }}>
        <Table
          columns={columns}
          dataSource={products}
          rowKey="id"
          loading={loading}
          size="small"
          rowSelection={{
            selectedRowKeys,
            onChange: setSelectedRowKeys,
          }}
          expandable={{
            expandedRowRender,
            expandedRowKeys: expandedRows,
            onExpand: (expanded, record) => {
              setExpandedRows(expanded
                ? [...expandedRows, record.id]
                : expandedRows.filter(id => id !== record.id))
            },
          }}
          pagination={{
            current: page,
            total,
            pageSize,
            size: 'small',
            showTotal: t => `共 ${t} 件商品`,
            onChange: p => fetchProducts(p),
          }}
          locale={{
            emptyText: (
              <Empty
                description="暂无商品数据"
                style={{ padding: '40px 0' }}
              >
                <Button type="primary" icon={<SyncOutlined />}
                  onClick={() => handleSync(true)}>
                  立即同步平台商品
                </Button>
              </Empty>
            )
          }}
        />
      </Card>

      {/* 铺货弹窗 */}
      <Modal
        title={`铺货（${spreadItems.length}个商品）`}
        open={spreadModal}
        onOk={handleSpreadSubmit}
        onCancel={() => setSpreadModal(false)}
        confirmLoading={spreading}
        okText="开始铺货"
        width={480}
        destroyOnClose
      >
        <Form form={spreadForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="dst_shop_ids" label="目标店铺"
            rules={[{ required: true, message: '请选择目标店铺' }]}>
            <Select mode="multiple" placeholder="选择要铺货到的店铺">
              <Option value={1}>WB 店铺B</Option>
              <Option value={2}>Ozon 店铺C</Option>
            </Select>
          </Form.Item>
          <Form.Item name="price_mode" label="价格设置" initialValue="original">
            <Select>
              <Option value="original">原价复制</Option>
              <Option value="auto">按佣金自动调整</Option>
              <Option value="manual">手动设置</Option>
            </Select>
          </Form.Item>
          <Form.Item
            noStyle
            shouldUpdate={(prev, curr) => prev.price_mode !== curr.price_mode}
          >
            {({ getFieldValue }) =>
              getFieldValue('price_mode') === 'manual' ? (
                <Form.Item name="manual_price" label="目标价格(₽)">
                  <InputNumber min={1} style={{ width: '100%' }} addonBefore="₽" />
                </Form.Item>
              ) : null
            }
          </Form.Item>
          <Alert
            type="info"
            showIcon={false}
            style={{ fontSize: 12, marginTop: 8 }}
            message="铺货任务将在后台异步执行，完成后推送企业微信通知"
          />
        </Form>
      </Modal>

      {/* AI改写描述抽屉 */}
      <Drawer
        title="AI改写商品描述"
        open={descDrawer}
        onClose={() => { setDescDrawer(false); setGeneratedDesc('') }}
        width={500}
        extra={
          <Button type="primary" icon={<RobotOutlined />}
            loading={descLoading} onClick={handleGenerateDesc}>
            生成
          </Button>
        }
      >
        {descListing && (
          <div>
            <div style={{ marginBottom: 12 }}>
              <Text style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>
                商品：{descListing.title_ru || descListing.platform_product_id}
              </Text>
            </div>
            <div style={{ marginBottom: 12 }}>
              <Text style={{ fontSize: 13, fontWeight: 500 }}>目标平台</Text>
              <Select value={descPlatform} onChange={setDescPlatform}
                style={{ width: '100%', marginTop: 6 }}>
                <Option value="wb">WB（简洁直接，200-500字）</Option>
                <Option value="ozon">Ozon（详细结构化，500-1000字）</Option>
                <Option value="yandex">Yandex（SEO导向，300-600字）</Option>
              </Select>
            </div>
            <div style={{ marginBottom: 12 }}>
              <Text style={{ fontSize: 13, fontWeight: 500 }}>原描述</Text>
              <div style={{
                marginTop: 6, padding: 10, fontSize: 12,
                background: 'var(--color-background-secondary)',
                borderRadius: 8, color: 'var(--color-text-secondary)',
                maxHeight: 120, overflow: 'auto',
              }}>
                {descListing.description_ru || '暂无描述'}
              </div>
            </div>
            {descLoading && (
              <div style={{ textAlign: 'center', padding: 20 }}>
                <Spin tip="AI改写中..." />
              </div>
            )}
            {generatedDesc && (
              <div>
                <Text style={{ fontSize: 13, fontWeight: 500 }}>改写结果</Text>
                <div style={{
                  marginTop: 6, padding: 10, fontSize: 12,
                  background: 'var(--color-background-info)',
                  borderRadius: 8, color: 'var(--color-text-primary)',
                  maxHeight: 300, overflow: 'auto', lineHeight: 1.7,
                }}>
                  {generatedDesc}
                </div>
                <Button type="primary" style={{ marginTop: 8 }}
                  onClick={() => {
                    message.success('描述已保存')
                    setDescDrawer(false)
                  }}>
                  保存此描述
                </Button>
              </div>
            )}
          </div>
        )}
      </Drawer>
    </div>
  )
}

export default Products
