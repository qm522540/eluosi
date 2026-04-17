import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Typography, Card, Table, Button, Tag, Space, Row, Col,
  Input, Select, InputNumber, Modal, Form, Tooltip, Empty,
  Badge, message, Alert, Spin, Drawer, Divider, Image, Switch,
} from 'antd'
import {
  SyncOutlined, PlusOutlined, EditOutlined,
  RobotOutlined, SendOutlined, ShopOutlined,
} from '@ant-design/icons'
import {
  getProducts, syncProducts, checkSyncNeeded,
  updateProductMargin, generateDescription, optimizeTitle,
  spreadProducts, getSpreadRecords, updateProduct, updateListing,
  downloadProductImages, getProductPlatformAttributes,
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

// ========== 编辑弹窗辅助组件 ==========

const SectionTitle = ({ children, right, tip }) => (
  <div style={{
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    marginBottom: 12, paddingBottom: 6,
    borderBottom: '2px solid #f0f0f0',
  }}>
    <div style={{ fontSize: 14, fontWeight: 600, color: '#1f1f1f' }}>
      {children}
      {tip && (
        <span style={{ marginLeft: 8, fontSize: 12, color: '#888', fontWeight: 400 }}>
          {tip}
        </span>
      )}
    </div>
    {right}
  </div>
)

const FieldLabelWithAI = ({ title, onClick, loading, aiText }) => (
  <Space size={8}>
    <span>{title}</span>
    <Button
      size="small" type="link" icon={<RobotOutlined />}
      onClick={onClick} loading={loading}
      style={{ padding: 0, height: 'auto' }}
    >
      {aiText}
    </Button>
  </Space>
)

const AISuggestionCard = ({ color, platform, text, onRegenerate, regenerating, onClose, scrollable }) => {
  const scheme = color === 'green'
    ? { bg: '#f6ffed', border: '#b7eb8f', headColor: '#389e0d' }
    : { bg: '#f0f7ff', border: '#bae0ff', headColor: '#0958d9' }
  return (
    <div style={{
      marginTop: 8, padding: '10px 12px',
      background: scheme.bg, border: `1px solid ${scheme.border}`,
      borderRadius: 6,
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        fontSize: 12, color: scheme.headColor, marginBottom: 6, fontWeight: 500,
      }}>
        <span>🤖 AI 优化建议（{platform?.toUpperCase() || ''} 风格）— 已填入上方</span>
        <Space size={4}>
          <Button size="small" type="text" onClick={onRegenerate} loading={regenerating}
            style={{ fontSize: 11, height: 22, padding: '0 6px' }}>
            重新生成
          </Button>
          <Button size="small" type="text" onClick={onClose}
            style={{ fontSize: 11, height: 22, padding: '0 6px', color: '#888' }}>
            关闭
          </Button>
        </Space>
      </div>
      <div style={{
        fontSize: 12, lineHeight: 1.6, color: '#1f1f1f',
        whiteSpace: 'pre-wrap',
        ...(scrollable ? { maxHeight: 180, overflow: 'auto' } : {}),
      }}>
        {text}
      </div>
    </div>
  )
}

// ========== 平台属性展示块（懒加载） ==========

const PlatformAttributesBlock = ({ productId }) => {
  const [attrs, setAttrs] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!productId) return
    setLoading(true)
    setError(null)
    getProductPlatformAttributes(productId)
      .then(res => setAttrs(res.data))
      .catch(e => setError(e?.response?.data?.msg || '拉取失败'))
      .finally(() => setLoading(false))
  }, [productId])

  if (!productId) return null

  return (
    <>
      <SectionTitle tip={attrs?.platform?.toUpperCase()}>平台商品属性</SectionTitle>
      {loading ? (
        <div style={{ textAlign: 'center', padding: 20 }}>
          <Spin size="small" tip="正在拉取平台属性..." />
        </div>
      ) : error ? (
        <Alert type="warning" message={error} style={{ fontSize: 12 }} />
      ) : attrs?.attributes?.length > 0 ? (
        <div style={{
          background: '#fafafa', border: '1px solid #f0f0f0',
          borderRadius: 8, padding: 12, maxHeight: 300, overflowY: 'auto',
        }}>
          {attrs.attributes.map((a, i) => (
            <div key={i} style={{
              display: 'flex', gap: 8, padding: '5px 0',
              borderBottom: i < attrs.attributes.length - 1 ? '1px solid #f5f5f5' : 'none',
              fontSize: 12,
            }}>
              <div style={{
                minWidth: 140, maxWidth: 180, color: '#666',
                fontWeight: 500, flexShrink: 0,
              }}>
                {a.name}
              </div>
              <div style={{ color: '#1f1f1f', wordBreak: 'break-word' }}>
                {a.value || '-'}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ fontSize: 12, color: '#999', padding: '8px 0' }}>
          该商品暂无平台属性数据
        </div>
      )}
    </>
  )
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
  // AI 描述优化
  const [descOptimizing, setDescOptimizing] = useState(false)
  const [optimizedDesc, setOptimizedDesc] = useState(null)
  // OSS 图片归档
  const [imagesArchiving, setImagesArchiving] = useState(false)
  const [archivedImages, setArchivedImages] = useState(null)

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
    setOptimizedDesc(null)
    // 若 listing.oss_images 已有归档数据，直接展示
    const firstL = (record.listings || [])[0]
    setArchivedImages(firstL?.oss_images || null)
    const firstListing = (record.listings || [])[0]
    editForm.setFieldsValue({
      sku: record.sku,
      platform_product_id: firstListing?.platform_product_id || '',
      name_zh: record.name_zh,
      name_ru: record.name_ru || firstListing?.title_ru || '',
      description_ru: firstListing?.description_ru || '',
      local_category_id: record.local_category_id,
      cost_price: record.cost_price,
      net_margin: record.net_margin ? Math.round(record.net_margin * 100) : null,
      weight_g: record.weight_g,
      length_mm: record.length_mm,
      width_mm: record.width_mm,
      height_mm: record.height_mm,
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
      const newTitle = res.data?.optimized_title || ''
      if (newTitle) {
        // 直接填入文本框 + 保留建议展示框（对比原值）
        editForm.setFieldsValue({ name_ru: newTitle })
        setOptimizedTitle(newTitle)
        message.success('AI 已生成并填入，可直接保存或继续编辑')
      } else {
        message.warning('AI 未返回内容')
      }
    } catch {
      message.error('AI 标题优化失败')
    } finally {
      setTitleOptimizing(false)
    }
  }

  const handleEditSubmit = async () => {
    try {
      const values = await editForm.validateFields()
      setEditSubmitting(true)
      const productPayload = {
        name_zh: values.name_zh,
        name_ru: values.name_ru,
        local_category_id: values.local_category_id,
        cost_price: values.cost_price,
        net_margin: values.net_margin ? values.net_margin / 100 : null,
        weight_g: values.weight_g,
        length_mm: values.length_mm,
        width_mm: values.width_mm,
        height_mm: values.height_mm,
        image_url: values.image_url,
      }
      const tasks = [updateProduct(editingProduct.id, productPayload)]
      // 标题/描述同时更新到当前店铺的 listing
      const firstListing = (editingProduct.listings || [])[0]
      if (firstListing) {
        const listingPayload = {}
        if (values.name_ru !== (editingProduct.name_ru || firstListing.title_ru)) {
          listingPayload.title_ru = values.name_ru
        }
        if (values.description_ru !== (firstListing.description_ru || '')) {
          listingPayload.description_ru = values.description_ru
        }
        if (Object.keys(listingPayload).length > 0) {
          tasks.push(updateListing(firstListing.id, listingPayload))
        }
      }
      await Promise.all(tasks)
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

  const handleArchiveImages = async () => {
    if (!editingProduct) return
    setImagesArchiving(true)
    try {
      const res = await downloadProductImages(editingProduct.id)
      const urls = res.data?.oss_images || []
      setArchivedImages(urls)
      message.success(`已归档 ${urls.length} 张图片到 OSS`)
      // 刷新编辑的 product 对象（让第一张 OSS 图变成新的 image_url）
      if (urls[0]) {
        editForm.setFieldsValue({ image_url: urls[0] })
      }
    } catch (e) {
      message.error(e?.response?.data?.msg || '图片归档失败')
    } finally {
      setImagesArchiving(false)
    }
  }

  const handleOptimizeDesc = async () => {
    const firstListing = (editingProduct?.listings || [])[0]
    if (!firstListing) {
      message.warning('此商品没有关联 listing，无法优化')
      return
    }
    setDescOptimizing(true)
    setOptimizedDesc(null)
    try {
      const res = await generateDescription(firstListing.id, firstListing.platform)
      const newDesc = res.data?.description || ''
      if (newDesc) {
        editForm.setFieldsValue({ description_ru: newDesc })
        setOptimizedDesc(newDesc)
        message.success('AI 已生成并填入，可直接保存或继续编辑')
      } else {
        message.warning('AI 未返回内容')
      }
    } catch {
      message.error('AI 描述优化失败')
    } finally {
      setDescOptimizing(false)
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
        price_mode: values.price_mode || 'auto',
        manual_price: values.manual_price,
        commission_wb: values.commission_wb,
        commission_ozon: values.commission_ozon,
        commission_yandex: values.commission_yandex,
        ai_rewrite_title: values.ai_rewrite_title || false,
        ai_rewrite_desc: values.ai_rewrite_desc || false,
        use_oss_images: values.use_oss_images || false,
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

      {/* ==================== 商品编辑抽屉（85% 宽） ==================== */}
      <Drawer
        title={
          <Space>
            <EditOutlined style={{ color: '#1677ff' }} />
            <span>编辑商品</span>
            {editingProduct && (
              <>
                <Tag color="default" style={{ fontSize: 11, marginLeft: 4 }}>
                  {editingProduct.sku}
                </Tag>
                {editingProduct.listings?.[0]?.platform && (
                  <Tag color={PLATFORM_COLOR[editingProduct.listings[0].platform]?.color || 'default'}
                    style={{ fontSize: 11 }}>
                    {PLATFORM_COLOR[editingProduct.listings[0].platform]?.label}
                  </Tag>
                )}
              </>
            )}
          </Space>
        }
        open={editModal}
        onClose={() => { setEditModal(false); editForm.resetFields() }}
        width="85%"
        destroyOnClose
        extra={
          <Space>
            <Button onClick={() => { setEditModal(false); editForm.resetFields() }}>
              取消
            </Button>
            <Button type="primary" loading={editSubmitting} onClick={handleEditSubmit}>
              保存
            </Button>
          </Space>
        }
      >
        <Form form={editForm} layout="vertical">

          {/* ========== 顶部分组 1：基本信息（宽屏展开，4 列）========== */}
          <SectionTitle>基本信息</SectionTitle>
          <Row gutter={16}>
            <Col span={6}>
              <Form.Item name="sku" label="卖家商品编码">
                <Input disabled />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item
                name="platform_product_id"
                label={
                  <Space size={4}>
                    <span>平台编码</span>
                    <span style={{ fontSize: 11, color: '#888', fontWeight: 'normal' }}>
                      ({editingProduct?.listings?.[0]?.platform?.toUpperCase() || ''})
                    </span>
                  </Space>
                }
              >
                <Input disabled />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="local_category_id" label="本地分类">
                <Select
                  allowClear showSearch optionFilterProp="children"
                  placeholder="选择本地统一分类"
                >
                  {localCategories.map(c => (
                    <Option key={c.id} value={c.id}>
                      {c.name} {c.name_ru ? `（${c.name_ru}）` : ''}
                    </Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item
                name="name_zh" label="中文名（本地备注）"
                rules={[{ required: true, message: '请填中文名' }]}
              >
                <Input placeholder="方便自己识别的中文名称" />
              </Form.Item>
            </Col>
          </Row>

          <Divider style={{ margin: '8px 0 20px' }} />

          {/* ========== 双栏：左文案 + 右图片 ========== */}
          <Row gutter={24}>
            {/* 左栏：平台文案 + 定价物流 */}
            <Col span={14}>
              <SectionTitle
                tip={editingProduct?.listings?.[0]?.platform
                  ? `${editingProduct.listings[0].platform.toUpperCase()} 平台文案`
                  : '平台文案'}
              >
                平台文案
              </SectionTitle>
              <Form.Item
                label={
                  <FieldLabelWithAI
                    title="商品标题"
                    onClick={handleOptimizeTitle}
                    loading={titleOptimizing}
                    aiText="AI 优化标题"
                  />
                }
                extra="平台上给买家看的俄文标题"
              >
                <Form.Item name="name_ru" noStyle>
                  <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} placeholder="商品俄文标题" />
                </Form.Item>
                {optimizedTitle && (
                  <AISuggestionCard
                    color="blue"
                    platform={editingProduct?.listings?.[0]?.platform}
                    text={optimizedTitle}
                    onRegenerate={handleOptimizeTitle}
                    regenerating={titleOptimizing}
                    onClose={() => setOptimizedTitle(null)}
                  />
                )}
              </Form.Item>
              <Form.Item
                label={
                  <FieldLabelWithAI
                    title="商品描述"
                    onClick={handleOptimizeDesc}
                    loading={descOptimizing}
                    aiText="AI 优化描述"
                  />
                }
                extra="平台详细描述（俄文）。保存后同步到 listing，下次同步可能被平台值覆盖"
              >
                <Form.Item name="description_ru" noStyle>
                  <Input.TextArea
                    autoSize={{ minRows: 8, maxRows: 20 }}
                    placeholder="商品详细描述（俄文）"
                  />
                </Form.Item>
                {optimizedDesc && (
                  <AISuggestionCard
                    color="green"
                    platform={editingProduct?.listings?.[0]?.platform}
                    text={optimizedDesc}
                    onRegenerate={handleOptimizeDesc}
                    regenerating={descOptimizing}
                    onClose={() => setOptimizedDesc(null)}
                    scrollable
                  />
                )}
              </Form.Item>

              <Divider style={{ margin: '16px 0 20px' }} />

              <SectionTitle>定价与物流</SectionTitle>

              {/* 平台同步字段（只读） */}
              {(() => {
                const l = editingProduct?.listings?.[0]
                const price = l?.price
                const discount = l?.discount_price
                const stock = l?.stock ?? 0
                const discountPct = (price && discount && price > discount)
                  ? Math.round(100 - (discount / price) * 100) : 0
                const stockColor = stock === 0 ? '#cf1322' : stock < 10 ? '#d46b08' : '#389e0d'
                return (
                  <div style={{
                    padding: '10px 14px', marginBottom: 16,
                    background: '#fafafa', border: '1px solid #f0f0f0',
                    borderRadius: 8,
                  }}>
                    <div style={{ fontSize: 11, color: '#888', marginBottom: 8 }}>
                      平台同步字段（只读）
                    </div>
                    <Row gutter={16}>
                      <Col span={8}>
                        <div style={{ fontSize: 12, color: '#666', marginBottom: 2 }}>平台原价</div>
                        <div style={{ fontSize: 18, fontWeight: 500, color: '#1f1f1f' }}>
                          {price ? `₽ ${Number(price).toLocaleString()}` : '-'}
                        </div>
                      </Col>
                      <Col span={8}>
                        <div style={{ fontSize: 12, color: '#666', marginBottom: 2 }}>
                          销售价
                          {discountPct > 0 && (
                            <Tag color="red" style={{ marginLeft: 6, fontSize: 10, padding: '0 4px', lineHeight: '16px' }}>
                              -{discountPct}%
                            </Tag>
                          )}
                        </div>
                        <div style={{ fontSize: 18, fontWeight: 500, color: discount ? '#cf1322' : '#1f1f1f' }}>
                          {discount
                            ? `₽ ${Number(discount).toLocaleString()}`
                            : price ? `₽ ${Number(price).toLocaleString()}` : '-'}
                        </div>
                      </Col>
                      <Col span={8}>
                        <div style={{ fontSize: 12, color: '#666', marginBottom: 2 }}>库存</div>
                        <div style={{ fontSize: 18, fontWeight: 500, color: stockColor }}>
                          {stock > 0 ? `${stock} 件` : '无货'}
                        </div>
                      </Col>
                    </Row>
                  </div>
                )
              })()}

              {/* 本地字段（可编辑） */}
              <Row gutter={16}>
                <Col span={8}>
                  <Form.Item
                    name="cost_price" label="成本价"
                    extra="本地字段，不同步平台；供毛利/ROAS 计算用"
                  >
                    <InputNumber min={0} step={0.01} style={{ width: '100%' }} addonBefore="₽" />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item
                    name="net_margin" label="净毛利率"
                    extra="AI 自主调价会依据此参数"
                  >
                    <InputNumber min={1} max={99} step={1} style={{ width: '100%' }} addonAfter="%" />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item
                    name="weight_g" label="重量"
                    extra="同步自动拉取，可手动覆盖"
                  >
                    <InputNumber min={0} step={1} style={{ width: '100%' }} addonAfter="g" />
                  </Form.Item>
                </Col>
              </Row>
              <Row gutter={16}>
                <Col span={8}>
                  <Form.Item name="length_mm" label="长" extra="WB 同步回填（mm）">
                    <InputNumber min={0} step={1} style={{ width: '100%' }} addonAfter="mm" />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name="width_mm" label="宽">
                    <InputNumber min={0} step={1} style={{ width: '100%' }} addonAfter="mm" />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name="height_mm" label="高">
                    <InputNumber min={0} step={1} style={{ width: '100%' }} addonAfter="mm" />
                  </Form.Item>
                </Col>
              </Row>

              <Divider style={{ margin: '8px 0 16px' }} />

              {/* ========== 平台属性（懒加载只读展示）========== */}
              <PlatformAttributesBlock productId={editingProduct?.id} />
            </Col>

            {/* 右栏：图片 */}
            <Col span={10}>
              <SectionTitle
                right={
                  <Button
                    size="small" icon={<RobotOutlined />}
                    onClick={handleArchiveImages}
                    loading={imagesArchiving}
                    type={archivedImages?.length ? 'default' : 'primary'}
                    ghost={!!archivedImages?.length}
                  >
                    {archivedImages?.length ? '重新归档' : '归档到 OSS'}
                  </Button>
                }
              >
                商品图片 {archivedImages?.length > 0 && (
                  <Tag color="success" style={{ marginLeft: 8 }}>
                    {archivedImages.length} 张
                  </Tag>
                )}
              </SectionTitle>
              {archivedImages?.length > 0 ? (
                <div style={{
                  padding: 14, background: '#fafafa',
                  border: '1px solid #f0f0f0', borderRadius: 8,
                }}>
                  <Image.PreviewGroup>
                    <div style={{ display: 'grid',
                      gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))',
                      gap: 12 }}>
                      {archivedImages.map((url, i) => (
                        <div key={i} style={{ position: 'relative' }}>
                          <Image
                            src={url}
                            alt={`img-${i}`}
                            width="100%"
                            height={130}
                            style={{ objectFit: 'cover', borderRadius: 6,
                              border: '1px solid #e8e8e8', background: '#fff' }}
                            preview={{ mask: <span style={{ fontSize: 12 }}>点击预览</span> }}
                          />
                          {i === 0 && (
                            <Tag color="blue" style={{
                              position: 'absolute', top: 6, left: 6,
                              fontSize: 10, margin: 0, padding: '0 6px',
                              lineHeight: '18px',
                            }}>主图</Tag>
                          )}
                        </div>
                      ))}
                    </div>
                  </Image.PreviewGroup>
                  <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginTop: 12 }}>
                    ✓ 已上传阿里云 OSS，铺货和外部展示可直接使用
                  </div>
                </div>
              ) : (
                <div style={{
                  padding: '40px 16px', textAlign: 'center',
                  background: '#fafafa', border: '1px dashed #d9d9d9',
                  borderRadius: 8,
                }}>
                  <div style={{ fontSize: 14, color: 'var(--color-text-secondary)', marginBottom: 8 }}>
                    还未归档
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                    图片目前只在平台 CDN 上，链接可能失效<br/>
                    点击右上「归档到 OSS」一键保存到阿里云
                  </div>
                </div>
              )}
              <Form.Item
                name="image_url" label="主图 URL"
                style={{ marginTop: 16, marginBottom: 0 }}
                extra="归档后自动改为 OSS 地址；或手动填外部 URL"
              >
                <Input placeholder="https://..." size="small" />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Drawer>

      {/* ==================== 铺货抽屉 ==================== */}
      <Drawer
        title={
          <Space>
            <SendOutlined style={{ color: '#1677ff' }} />
            <span>铺货到其他店铺</span>
            <Tag color="blue" style={{ marginLeft: 4 }}>共 {spreadItems.length} 个商品</Tag>
          </Space>
        }
        open={spreadModal}
        onClose={() => { setSpreadModal(false); spreadForm.resetFields() }}
        width="85%"
        destroyOnClose
        extra={
          <Space>
            <Button onClick={() => { setSpreadModal(false); spreadForm.resetFields() }}>
              取消
            </Button>
            <Button type="primary" loading={spreading}
              icon={<SendOutlined />} onClick={handleSpreadSubmit}>
              开始铺货
            </Button>
          </Space>
        }
      >
        <Row gutter={24}>
          {/* 左栏：铺货配置（14） */}
          <Col span={14}>
            <Form
              form={spreadForm} layout="vertical"
              initialValues={{
                price_mode: 'auto',
                commission_wb: 15,
                commission_ozon: 12,
                commission_yandex: 10,
                ai_rewrite_title: true,
                ai_rewrite_desc: true,
                use_oss_images: true,
              }}
            >
              <SectionTitle>目标店铺</SectionTitle>
              <Form.Item
                name="dst_shop_ids" label="选择要铺货到的店铺"
                rules={[{ required: true, message: '请至少选择一个目标店铺' }]}
                extra="支持多选，会并行铺到每个选中的店铺。已有该 SKU 的店铺会显示为灰色不可选"
              >
                <Select
                  mode="multiple" placeholder="选择要铺货到的店铺"
                  style={{ width: '100%' }}
                  optionFilterProp="children" showSearch
                >
                  {['wb', 'ozon', 'yandex'].map(plat => {
                    const list = shops.filter(s => s.platform === plat && s.status === 'active')
                    if (!list.length) return null
                    const cfg = PLATFORM_COLOR[plat] || {}
                    // 排除当前商品已在其中的店铺
                    const existingShopIds = new Set(
                      spreadItems.flatMap(l => l.shop_id ? [l.shop_id] : [])
                    )
                    return (
                      <Select.OptGroup key={plat} label={cfg.label}>
                        {list.map(s => (
                          <Option key={s.id} value={s.id}
                            disabled={existingShopIds.has(s.id)}>
                            {cfg.label} · {s.name}
                            {existingShopIds.has(s.id) && ' （已铺过）'}
                          </Option>
                        ))}
                      </Select.OptGroup>
                    )
                  })}
                </Select>
              </Form.Item>

              <Divider style={{ margin: '8px 0 16px' }} />

              <SectionTitle>价格策略</SectionTitle>
              <Form.Item name="price_mode" label="价格模式">
                <Select>
                  <Option value="auto">按目标平台佣金自动调整（推荐）</Option>
                  <Option value="original">原价复制（使用源店铺售价）</Option>
                  <Option value="manual">手动设置目标价</Option>
                </Select>
              </Form.Item>
              <Form.Item noStyle shouldUpdate={(p, c) => p.price_mode !== c.price_mode}>
                {({ getFieldValue }) => {
                  const mode = getFieldValue('price_mode')
                  if (mode === 'auto') return (
                    <Card size="small" style={{ marginBottom: 16, background: '#fafbff', borderColor: '#e6edff' }}>
                      <div style={{ fontSize: 12, color: '#666', marginBottom: 10 }}>
                        填入各平台佣金比例，系统按「保持毛利相同」原则自动折算目标售价。
                        佣金率按品类不同浮动（WB 4-25% / OZON 5-20% / Yandex 3-15%），请填你店铺实际类目的佣金
                      </div>
                      <Row gutter={12}>
                        <Col span={8}>
                          <Form.Item name="commission_wb" label={
                            <span style={{ color: PLATFORM_COLOR.wb.color }}>WB 佣金</span>
                          } style={{ marginBottom: 0 }}>
                            <InputNumber min={0} max={50} step={0.5}
                              style={{ width: '100%' }} addonAfter="%" />
                          </Form.Item>
                        </Col>
                        <Col span={8}>
                          <Form.Item name="commission_ozon" label={
                            <span style={{ color: PLATFORM_COLOR.ozon.color }}>OZON 佣金</span>
                          } style={{ marginBottom: 0 }}>
                            <InputNumber min={0} max={50} step={0.5}
                              style={{ width: '100%' }} addonAfter="%" />
                          </Form.Item>
                        </Col>
                        <Col span={8}>
                          <Form.Item name="commission_yandex" label={
                            <span style={{ color: PLATFORM_COLOR.yandex.color }}>Yandex 佣金</span>
                          } style={{ marginBottom: 0 }}>
                            <InputNumber min={0} max={50} step={0.5}
                              style={{ width: '100%' }} addonAfter="%" />
                          </Form.Item>
                        </Col>
                      </Row>
                    </Card>
                  )
                  if (mode === 'manual') return (
                    <Form.Item name="manual_price" label="目标价"
                      rules={[{ required: true, message: '请填目标价' }]}
                      style={{ marginBottom: 16 }}>
                      <InputNumber min={1} style={{ width: '100%' }} addonBefore="₽" />
                    </Form.Item>
                  )
                  return (
                    <div style={{
                      padding: '8px 12px', fontSize: 12, marginBottom: 16,
                      color: '#666', background: '#fafafa',
                      border: '1px solid #f0f0f0', borderRadius: 6,
                    }}>
                      直接复用源店铺当前售价，不做折算
                    </div>
                  )
                }}
              </Form.Item>

              <Divider style={{ margin: '8px 0 16px' }} />

              <SectionTitle tip="铺货时自动按目标平台风格处理内容">
                智能调整
              </SectionTitle>
              <Card size="small" style={{ marginBottom: 12, background: '#fafbff', borderColor: '#e6edff' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 500 }}>
                      <RobotOutlined style={{ color: '#1677ff', marginRight: 6 }} />
                      标题 AI 智能调整
                    </div>
                    <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>
                      按目标平台风格（WB 关键词前置 / Ozon SEO）自动优化标题
                    </div>
                  </div>
                  <Form.Item name="ai_rewrite_title" valuePropName="checked" noStyle>
                    <Switch />
                  </Form.Item>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 500 }}>
                      <RobotOutlined style={{ color: '#1677ff', marginRight: 6 }} />
                      描述 AI 智能调整
                    </div>
                    <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>
                      按目标平台风格重写详情描述（WB 简洁 / Ozon 结构化）
                    </div>
                  </div>
                  <Form.Item name="ai_rewrite_desc" valuePropName="checked" noStyle>
                    <Switch />
                  </Form.Item>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 500 }}>
                      <RobotOutlined style={{ color: '#1677ff', marginRight: 6 }} />
                      图片调整（使用 OSS 归档图）
                    </div>
                    <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>
                      优先上传 OSS 归档的图片（未归档则用平台原图链接）
                    </div>
                  </div>
                  <Form.Item name="use_oss_images" valuePropName="checked" noStyle>
                    <Switch />
                  </Form.Item>
                </div>
              </Card>

              <Alert
                type="info"
                showIcon
                style={{ fontSize: 12 }}
                message="铺货任务异步执行，完成后推送企业微信通知。AI 改写单商品约 3-10 秒"
              />
            </Form>
          </Col>

          {/* 右栏：来源商品预览 */}
          <Col span={10}>
            <SectionTitle>
              来源商品
              {spreadItems.length > 1 && (
                <Tag style={{ marginLeft: 8 }}>{spreadItems.length} 个</Tag>
              )}
            </SectionTitle>
            <div style={{
              padding: 12, background: '#fafafa',
              border: '1px solid #f0f0f0', borderRadius: 8,
              maxHeight: 'calc(100vh - 240px)', overflowY: 'auto',
            }}>
              {spreadItems.length === 0 ? (
                <Empty description="无商品" />
              ) : (
                spreadItems.map((l, idx) => {
                  const url = platformProductUrl(l.platform, l.platform_product_id, l)
                  const plat = PLATFORM_COLOR[l.platform] || {}
                  const displayPrice = l.discount_price || l.price
                  return (
                    <div key={l.id} style={{
                      display: 'flex', gap: 12,
                      padding: 10, background: '#fff',
                      borderRadius: 6, marginBottom: idx === spreadItems.length - 1 ? 0 : 10,
                      border: '1px solid #f0f0f0',
                    }}>
                      <Image
                        src={(l.oss_images && l.oss_images[0]) || ''}
                        fallback="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='80' height='80'%3E%3Crect width='80' height='80' fill='%23f5f5f5'/%3E%3Ctext x='50%25' y='50%25' font-size='11' fill='%23999' text-anchor='middle' dy='.3em'%3E无图%3C/text%3E%3C/svg%3E"
                        width={80} height={80}
                        style={{ objectFit: 'cover', borderRadius: 4, flexShrink: 0 }}
                        preview={{ mask: <span style={{ fontSize: 11 }}>预览</span> }}
                      />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 500,
                          overflow: 'hidden', textOverflow: 'ellipsis',
                          display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
                          {l.title_ru || '(无标题)'}
                        </div>
                        <div style={{ fontSize: 11, color: '#888', marginTop: 4, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                          <Tag color={plat.color} style={{ margin: 0, fontSize: 10, padding: '0 4px', lineHeight: '16px' }}>
                            {plat.label}
                          </Tag>
                          <span>ID: {l.platform_product_id}</span>
                          {displayPrice != null && (
                            <span style={{ color: '#cf1322', fontWeight: 500 }}>
                              ₽{Math.round(displayPrice)}
                            </span>
                          )}
                          {l.oss_images?.length > 0 && (
                            <Tag color="success" style={{ margin: 0, fontSize: 10, padding: '0 4px', lineHeight: '16px' }}>
                              OSS {l.oss_images.length} 张
                            </Tag>
                          )}
                        </div>
                        {url && (
                          <a href={url} target="_blank" rel="noopener noreferrer"
                             style={{ fontSize: 11, marginTop: 4, display: 'inline-block' }}>
                            在平台查看 →
                          </a>
                        )}
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </Col>
        </Row>
      </Drawer>

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
