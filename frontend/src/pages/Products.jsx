import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Typography, Card, Table, Button, Tag, Space, Row, Col,
  Input, Select, InputNumber, Modal, Form, Tooltip, Empty,
  Badge, message, Alert, Spin, Drawer,
} from 'antd'
import {
  SyncOutlined, PlusOutlined, EditOutlined,
  RobotOutlined, SendOutlined, ShopOutlined,
} from '@ant-design/icons'
import {
  getProducts, syncProducts, checkSyncNeeded,
  updateProductMargin, generateDescription, optimizeTitle,
  spreadProducts, getSpreadRecords, updateProduct,
} from '@/api/products'
import { getShops } from '@/api/shops'
import { listLocalCategories } from '@/api/mapping'
import { useAuthStore } from '@/stores/authStore'

const { Text } = Typography
const { Option } = Select

const PLATFORM_COLOR = {
  wb: { bg: '#FBEAF0', color: '#993556', label: 'WB' },
  ozon: { bg: '#E6F1FB', color: '#185FA5', label: 'Ozon' },
  yandex: { bg: '#FAEEDA', color: '#633806', label: 'YM' },
}

// 根据平台 + 平台商品ID 生成前台商品详情页链接
const platformProductUrl = (platform, platformProductId, listing) => {
  if (listing?.url) return listing.url
  if (!platformProductId) return null
  if (platform === 'wb') {
    return `https://www.wildberries.ru/catalog/${platformProductId}/detail.aspx`
  }
  if (platform === 'ozon') {
    return `https://www.ozon.ru/product/${platformProductId}/`
  }
  if (platform === 'yandex') {
    return `https://market.yandex.ru/product/${platformProductId}`
  }
  return null
}

const STATUS_MAP = {
  active: { color: 'success', label: '在售' },
  inactive: { color: 'default', label: '停售' },
  out_of_stock: { color: 'warning', label: '缺货' },
  blocked: { color: 'error', label: '封禁' },
}

// 简易相对时间：UTC 字符串 → "x 分钟前 / x 小时前 / YYYY-MM-DD HH:mm"
const dayjsLike = (iso) => {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  const diff = (Date.now() - t) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.round(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.round(diff / 3600)} 小时前`
  const d = new Date(iso)
  const pad = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
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

  // 商品编辑弹窗
  const [editModal, setEditModal] = useState(false)
  const [editingProduct, setEditingProduct] = useState(null)
  const [editForm] = Form.useForm()
  const [editSubmitting, setEditSubmitting] = useState(false)
  const [localCategories, setLocalCategories] = useState([])
  // AI 标题优化
  const [titleOptimizing, setTitleOptimizing] = useState(false)
  const [optimizedTitle, setOptimizedTitle] = useState(null)

  const fetchProducts = useCallback(async (p = 1) => {
    if (!filters.shop_id) {
      setProducts([])
      setTotal(0)
      return
    }
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
    if (filters.shop_id) {
      fetchProducts(1)
    } else {
      setProducts([])
      setTotal(0)
    }
  }, [fetchProducts, filters.shop_id])

  useEffect(() => {
    getShops({ page: 1, page_size: 100 }).then(res => {
      setShops(res.data?.items || [])
    }).catch(() => setShops([]))
    // 本地分类下拉数据（编辑商品用）
    listLocalCategories().then(res => {
      setLocalCategories(res.data?.items || [])
    }).catch(() => setLocalCategories([]))
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

  const handleEdit = (record) => {
    setEditingProduct(record)
    setOptimizedTitle(null)
    editForm.setFieldsValue({
      sku: record.sku,
      name_zh: record.name_zh,
      name_ru: record.name_ru,
      brand: record.brand,
      local_category_id: record.local_category_id,
      cost_price: record.cost_price,
      net_margin: record.net_margin ? Math.round(record.net_margin * 100) : null,
      weight_g: record.weight_g,
      image_url: record.image_url,
    })
    setEditModal(true)
  }

  const handleOptimizeTitle = async () => {
    const firstListing = (editingProduct?.listings || [])[0]
    if (!firstListing) {
      message.warning('此商品没有关联 listing，无法优化')
      return
    }
    setTitleOptimizing(true)
    setOptimizedTitle(null)
    try {
      const res = await optimizeTitle(firstListing.id)
      setOptimizedTitle(res.data?.optimized_title || '')
    } catch {
      message.error('AI 标题优化失败')
    } finally {
      setTitleOptimizing(false)
    }
  }

  const handleCopyOptimized = () => {
    if (!optimizedTitle) return
    try {
      navigator.clipboard.writeText(optimizedTitle)
      message.success('已复制，粘贴到平台后台即可')
    } catch {
      message.error('复制失败，请手动选中文本复制')
    }
  }

  const handleEditSubmit = async () => {
    try {
      const values = await editForm.validateFields()
      setEditSubmitting(true)
      const payload = {
        name_zh: values.name_zh,
        name_ru: values.name_ru,
        brand: values.brand,
        local_category_id: values.local_category_id,
        cost_price: values.cost_price,
        net_margin: values.net_margin ? values.net_margin / 100 : null,
        weight_g: values.weight_g,
        image_url: values.image_url,
      }
      await updateProduct(editingProduct.id, payload)
      message.success('商品已更新')
      setEditModal(false)
      editForm.resetFields()
      fetchProducts(page)
    } catch (e) {
      if (e.errorFields) return
      message.error('更新失败')
    } finally {
      setEditSubmitting(false)
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
      dataIndex: 'name_zh',
      width: 260,
      render: (_, record) => {
        const firstListing = (record.listings || [])[0]
        const url = firstListing ? platformProductUrl(
          firstListing.platform, firstListing.platform_product_id, firstListing
        ) : null
        const imgElement = record.image_url ? (
          <img src={record.image_url} alt=""
            style={{ width: 40, height: 40, objectFit: 'cover',
              borderRadius: 6, border: '0.5px solid var(--color-border-tertiary)' }} />
        ) : (
          <div style={{ width: 40, height: 40, background: 'var(--color-background-secondary)',
            borderRadius: 6, border: '0.5px solid var(--color-border-tertiary)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 10, color: 'var(--color-text-tertiary)' }}>图</div>
        )
        // 主标题：中文名，如果没有就退到俄文名或 SKU
        const mainTitle = record.name_zh || record.name_ru || record.sku
        // 副标题：俄文名（如果跟主标题不一致）
        const hasRuDifferent = record.name_ru && record.name_ru !== mainTitle
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {url ? (
              <a href={url} target="_blank" rel="noopener noreferrer"
                 style={{ display: 'inline-block', lineHeight: 0 }}
                 title="打开平台商品页">
                {imgElement}
              </a>
            ) : imgElement}
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontWeight: 500, fontSize: 13, lineHeight: 1.4 }}>
                {url ? (
                  <a href={url} target="_blank" rel="noopener noreferrer"
                     style={{ color: 'inherit' }}
                     title="打开平台商品页">
                    {mainTitle}
                  </a>
                ) : mainTitle}
              </div>
              {hasRuDifferent && (
                <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)',
                  lineHeight: 1.4, overflow: 'hidden', textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap' }}
                  title={record.name_ru}>
                  {record.name_ru}
                </div>
              )}
              <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>
                {(record.listings || []).map((l, i) => (
                  <span key={l.id}>
                    {i > 0 && <span style={{ margin: '0 4px' }}>·</span>}
                    <span style={{ color: PLATFORM_COLOR[l.platform]?.color || 'inherit' }}>
                      {PLATFORM_COLOR[l.platform]?.label}: {l.platform_product_id}
                    </span>
                  </span>
                ))}
                {(record.listings?.length > 0) && (
                  <span style={{ margin: '0 4px' }}>·</span>
                )}
                {record.sku}
              </div>
            </div>
          </div>
        )
      },
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
      title: (
        <Tooltip title="平台同步的可售库存，只读。WB 聚合多仓库 quantity，OZON 聚合 FBO/FBS 的 present。">
          <span>库存 <span style={{ color: 'var(--color-text-tertiary)', fontSize: 11 }}>ⓘ</span></span>
        </Tooltip>
      ),
      width: 80,
      render: (_, record) => {
        const listing = (record.listings || [])[0]
        if (!listing) return <Text style={{ color: 'var(--color-text-tertiary)' }}>-</Text>
        const stock = listing.stock || 0
        const tipTime = listing.stock_updated_at
          ? dayjsLike(listing.stock_updated_at)
          : ''
        const tip = tipTime ? `库存更新：${tipTime}` : '暂未同步库存'
        if (stock === 0) {
          return (
            <Tooltip title={tip}>
              <Tag color="red" style={{ fontSize: 11, margin: 0 }}>无货</Tag>
            </Tooltip>
          )
        }
        const color = stock < 10 ? '#d46b08' : '#389e0d'
        return (
          <Tooltip title={tip}>
            <span style={{ color, fontWeight: 500, fontSize: 13 }}>
              {stock.toLocaleString()}
            </span>
          </Tooltip>
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
            onClick={() => handleEdit(record)}>编辑</Button>
          <Button size="small" type="primary"
            style={{ background: '#185FA5', borderColor: '#185FA5' }}
            icon={<SendOutlined />}
            onClick={() => handleSpread(record.listings || [])}>
            铺货
          </Button>
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
            allowClear
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
                description={filters.shop_id ? '该店铺暂无商品，可点"手动同步"拉取' : '请先在上方选择店铺'}
                style={{ padding: '40px 0' }}
              >
                {filters.shop_id ? (
                  <Button type="primary" icon={<SyncOutlined />}
                    onClick={() => handleSync(true)}>
                    立即同步平台商品
                  </Button>
                ) : null}
              </Empty>
            )
          }}
        />
      </Card>

      {/* 商品编辑弹窗 */}
      <Modal
        title="编辑商品"
        open={editModal}
        onOk={handleEditSubmit}
        onCancel={() => { setEditModal(false); editForm.resetFields() }}
        confirmLoading={editSubmitting}
        okText="保存"
        cancelText="取消"
        width={560}
        destroyOnClose
      >
        <Form form={editForm} layout="vertical" style={{ marginTop: 12 }}>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="sku" label="SKU（只读）">
                <Input disabled />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="brand" label="品牌（平台同步，只读）">
                <Input disabled />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="name_zh"
            label="中文名"
            extra="本地备注使用，不同步平台。列表和搜索会用到，填一个方便自己识别的名字就行"
            rules={[{ required: true, message: '请填中文名' }]}
          >
            <Input placeholder="方便自己识别的中文名称" />
          </Form.Item>
          <Form.Item
            label={
              <Space size={8}>
                <span>商品标题（平台）</span>
                <Button
                  size="small" type="link" icon={<RobotOutlined />}
                  onClick={handleOptimizeTitle}
                  loading={titleOptimizing}
                  style={{ padding: 0, height: 'auto' }}
                >
                  AI 优化标题
                </Button>
              </Space>
            }
            extra="平台上给俄罗斯买家看的标题，本地只读。AI 优化会按当前店铺平台（WB / OZON）的风格给出建议，复制后到平台后台修改"
          >
            <Form.Item name="name_ru" noStyle>
              <Input disabled />
            </Form.Item>
            {optimizedTitle !== null && (
              <div style={{
                marginTop: 8, padding: '8px 12px',
                background: '#f0f7ff', border: '1px solid #bae0ff',
                borderRadius: 6,
              }}>
                <div style={{ fontSize: 12, color: '#0958d9', marginBottom: 4, fontWeight: 500 }}>
                  🤖 AI 优化建议（{editingProduct?.listings?.[0]?.platform?.toUpperCase() || ''} 风格）
                </div>
                <div style={{ fontSize: 13, lineHeight: 1.5, color: '#1f1f1f' }}>
                  {optimizedTitle || <span style={{ color: '#999' }}>AI 未返回内容</span>}
                </div>
                {optimizedTitle && (
                  <Space size={6} style={{ marginTop: 6 }}>
                    <Button size="small" type="primary" ghost onClick={handleCopyOptimized}>
                      复制
                    </Button>
                    <Button size="small" onClick={handleOptimizeTitle} loading={titleOptimizing}>
                      重新生成
                    </Button>
                    <Button size="small" type="link" onClick={() => setOptimizedTitle(null)}>
                      关闭
                    </Button>
                  </Space>
                )}
              </div>
            )}
          </Form.Item>
          <Form.Item name="local_category_id" label="本地分类">
            <Select
              allowClear
              showSearch
              optionFilterProp="children"
              placeholder="选择本地统一分类"
            >
              {localCategories.map(c => (
                <Option key={c.id} value={c.id}>
                  {c.name} {c.name_ru ? `（${c.name_ru}）` : ''}
                </Option>
              ))}
            </Select>
          </Form.Item>
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="cost_price" label="成本价（₽）">
                <InputNumber min={0} step={0.01} style={{ width: '100%' }} addonBefore="₽" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="net_margin"
                label="净毛利率"
                extra="AI 自主调价会依据此参数决定出价上限"
              >
                <InputNumber min={1} max={99} step={1} style={{ width: '100%' }} addonAfter="%" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="weight_g"
                label="重量"
                extra="同步时从平台自动拉取（WB 毛重 / OZON 体积重），可手动覆盖"
              >
                <InputNumber min={0} step={1} style={{ width: '100%' }} addonAfter="g" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="image_url" label="图片 URL">
            <Input placeholder="https://..." />
          </Form.Item>
          <Alert
            type="info"
            showIcon={false}
            style={{ fontSize: 12, marginTop: -8 }}
            message="平台商品ID、售价、状态等由同步决定，本页不可编辑"
          />
        </Form>
      </Modal>

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
