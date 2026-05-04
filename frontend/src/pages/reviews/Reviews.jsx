import { useState, useEffect, useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Typography, Card, Table, Button, Space, Select, Tag, Rate, Badge,
  Input, Segmented, message, Tooltip, Avatar,
} from 'antd'
import {
  CommentOutlined, SyncOutlined, SettingOutlined, RobotOutlined,
  WomanOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { getShops } from '@/api/shops'
import { listReviews, syncReviews } from '@/api/reviews'
import ReviewDetailDrawer from './components/ReviewDetailDrawer'
import SettingsModal from './components/SettingsModal'

const { Title, Text } = Typography
const { Option } = Select

const PLATFORM_TAG = {
  wb:   { color: '#CB11AB', label: 'WB' },
  ozon: { color: '#005BFF', label: 'Ozon' },
}

const SENTIMENT_META = {
  positive: { color: 'success', label: '好评 😊' },
  neutral:  { color: 'default', label: '中评 😐' },
  negative: { color: 'error',   label: '差评 😞' },
  unknown:  { color: 'default', label: '未分析' },
}

const STATUS_META = {
  unread:        { color: 'processing', label: '未读' },
  read:          { color: 'default',    label: '已读' },
  replied:       { color: 'success',    label: '已回复' },
  auto_replied:  { color: 'cyan',       label: '自动已回' },
  ignored:       { color: 'default',    label: '已忽略' },
}

const Reviews = () => {
  const [searchParams] = useSearchParams()
  const [shops, setShops] = useState([])
  const [shopId, setShopId] = useState(null)
  const [shopPlatform, setShopPlatform] = useState(null)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)

  // 过滤
  const [statusFilter, setStatusFilter] = useState(null)
  const [ratingFilter, setRatingFilter] = useState(null)
  const [sentimentFilter, setSentimentFilter] = useState(null)
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  // 详情抽屉
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [activeReview, setActiveReview] = useState(null)

  useEffect(() => {
    getShops({ page: 1, page_size: 100 })
      .then(r => {
        const items = (r.data?.items || []).filter(s => ['wb', 'ozon'].includes(s.platform))
        setShops(items)
        // 默认不自动选店, 等用户手动选 (避免误以为别店数据是当前店)
        // 仅当 URL 显式带 ?shopId=N 时才自动选
        const urlShopId = Number(searchParams.get('shopId'))
        const preferId = urlShopId && items.find(s => s.id === urlShopId)
          ? urlShopId
          : null
        if (preferId && !shopId) {
          setShopId(preferId)
          setShopPlatform(items.find(s => s.id === preferId)?.platform || null)
        }
      })
      .catch(() => setShops([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fetchData = useCallback(async () => {
    if (!shopId) return
    setLoading(true)
    try {
      const params = { page, page_size: pageSize }
      if (statusFilter) params.status = statusFilter
      if (ratingFilter) params.rating = ratingFilter
      if (sentimentFilter) params.sentiment = sentimentFilter
      if (keyword.trim()) params.keyword = keyword.trim()
      const r = await listReviews(shopId, params)
      setData(r.data)
    } catch (e) {
      message.error(e?.message || '加载失败')
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [shopId, page, pageSize, statusFilter, ratingFilter, sentimentFilter, keyword])

  useEffect(() => { fetchData() }, [fetchData])

  const handleShopChange = (val) => {
    const s = shops.find(x => x.id === val)
    setShopId(val)
    setShopPlatform(s?.platform || null)
    setPage(1)
  }

  const handleSync = async () => {
    if (!shopId) { message.warning('请先选择店铺'); return }
    setSyncing(true)
    try {
      // only_unanswered=false → 未回 + 已回都拉 (WB 内部分两次合并; Ozon 用 status=ALL)
      const r = await syncReviews(shopId, { only_unanswered: false, max_pages: 5 })
      const d = r.data || {}
      message.success(
        `同步完成: 新增 ${d.new || 0} / 更新 ${d.updated || 0} / 翻译 ${d.translated || 0}`,
        5,
      )
      fetchData()
    } catch (e) {
      message.error(e?.message || '同步失败', 6)
    } finally {
      setSyncing(false)
    }
  }

  const openDetail = (record) => {
    setActiveReview(record)
    setDrawerOpen(true)
  }

  const onDrawerClose = (changed) => {
    setDrawerOpen(false)
    setActiveReview(null)
    if (changed) fetchData()
  }

  const columns = useMemo(() => [
    {
      title: '平台',
      dataIndex: 'platform', width: 80,
      render: v => {
        const p = PLATFORM_TAG[v] || { color: 'default', label: v }
        return <Tag color={p.color} style={{ color: '#fff' }}>{p.label}</Tag>
      },
    },
    {
      title: '买家',
      dataIndex: 'customer_name', width: 110,
      render: (v) => v ? (
        <Space size={4}>
          <Avatar size="small" icon={<WomanOutlined />} style={{ background: '#f0a8b0' }} />
          <Text>{v}</Text>
        </Space>
      ) : <Text type="secondary">匿名</Text>,
    },
    {
      title: '星级',
      dataIndex: 'rating', width: 130,
      render: v => <Rate disabled value={v} style={{ fontSize: 14 }} />,
    },
    {
      title: '情感',
      dataIndex: 'sentiment', width: 90,
      render: v => {
        const m = SENTIMENT_META[v] || SENTIMENT_META.unknown
        return <Tag color={m.color}>{m.label}</Tag>
      },
    },
    {
      title: '评价内容',
      dataIndex: 'content_ru',
      render: (v, r) => (
        <div style={{ lineHeight: 1.4, maxWidth: 520 }}>
          <Text style={{ fontSize: 13 }}>{v}</Text>
          <div style={{ marginTop: 2 }}>
            <Text type="secondary" style={{ fontSize: 11 }}>
              {r.content_zh || <span style={{ color: '#ccc' }}>翻译中...</span>}
            </Text>
          </div>
          {r.platform_product_name && (
            <div style={{ marginTop: 2 }}>
              <Tooltip title={r.platform_product_name}>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  📦 {r.platform_product_name.slice(0, 40)}
                  {r.platform_product_name.length > 40 ? '…' : ''}
                </Text>
              </Tooltip>
            </div>
          )}
        </div>
      ),
    },
    {
      title: '时间',
      dataIndex: 'created_at_platform', width: 120,
      render: v => v ? <Text type="secondary" style={{ fontSize: 12 }}>
        {dayjs(v).format('MM-DD HH:mm')}
      </Text> : '—',
    },
    {
      title: '状态',
      dataIndex: 'status', width: 100,
      render: v => {
        const m = STATUS_META[v] || { color: 'default', label: v }
        return <Badge status={m.color} text={m.label} />
      },
    },
    {
      title: '操作', key: 'op', width: 110,
      render: (_, r) => (
        <Button size="small" type="link"
                icon={<RobotOutlined />}
                onClick={() => openDetail(r)}>
          {r.status === 'replied' || r.status === 'auto_replied' ? '查看' : '处理'}
        </Button>
      ),
    },
  ], [])

  const currentShop = shops.find(s => s.id === shopId)

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Title level={4} style={{ marginBottom: 4 }}>
          <CommentOutlined /> 评价管理
          <Text type="secondary" style={{ fontSize: 13, marginLeft: 12, fontWeight: 'normal' }}>
            买家评价拉取 · AI 翻译 · AI 起草友好+温暖回复 · 一键发送
          </Text>
        </Title>
        <Text type="secondary" style={{ fontSize: 12 }}>
          WB Feedbacks 实时拉取 / Ozon 需 Premium 订阅. 自动回复仅 4-5 星, 1-3 星人工处理.
        </Text>
      </div>

      <Card style={{ marginBottom: 12 }}>
        <Space wrap size={12}>
          <Select
            placeholder="选择店铺 (WB/Ozon)"
            style={{ width: 260 }}
            value={shopId}
            onChange={handleShopChange}
            showSearch optionFilterProp="children"
          >
            {shops.map(s => (
              <Option key={s.id} value={s.id}>
                [{PLATFORM_TAG[s.platform]?.label || s.platform}] {s.name}
              </Option>
            ))}
          </Select>

          <Segmented
            value={statusFilter || 'all'}
            onChange={v => { setStatusFilter(v === 'all' ? null : v); setPage(1) }}
            options={[
              { label: '全部', value: 'all' },
              { label: '未读', value: 'unread' },
              { label: '已读', value: 'read' },
              { label: '已回复', value: 'replied' },
            ]}
          />

          <Select
            placeholder="星级"
            style={{ width: 100 }}
            allowClear
            value={ratingFilter}
            onChange={v => { setRatingFilter(v); setPage(1) }}
          >
            {[5, 4, 3, 2, 1].map(n => (
              <Option key={n} value={n}>{n} ★</Option>
            ))}
          </Select>

          <Select
            placeholder="情感"
            style={{ width: 110 }}
            allowClear
            value={sentimentFilter}
            onChange={v => { setSentimentFilter(v); setPage(1) }}
          >
            <Option value="positive">好评</Option>
            <Option value="neutral">中评</Option>
            <Option value="negative">差评</Option>
          </Select>

          <Input
            placeholder="搜俄文/中文"
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            onPressEnter={fetchData}
            allowClear
            style={{ width: 180 }}
          />

          <Button type="primary"
                  icon={<SyncOutlined spin={syncing} />}
                  onClick={handleSync} loading={syncing}
                  disabled={!shopId}>
            手动同步
          </Button>

          <Button icon={<SettingOutlined />}
                  onClick={() => setSettingsOpen(true)}
                  disabled={!shopId}>
            设置
          </Button>
        </Space>
      </Card>

      {shopId && (
        <Card>
          <Table
            rowKey="id"
            columns={columns}
            dataSource={data?.items || []}
            loading={loading}
            pagination={{
              current: page, pageSize,
              total: data?.total || 0,
              showSizeChanger: true,
              pageSizeOptions: [10, 20, 50, 100],
              showTotal: (t) => `共 ${t} 条评价`,
              onChange: (p, ps) => {
                if (p !== page) setPage(p)
                if (ps !== pageSize) { setPageSize(ps); setPage(1) }
              },
            }}
            size="small"
            scroll={{ x: 'max-content' }}
            locale={{
              emptyText: shopId
                ? '暂无评价 — 点"手动同步"拉取最近买家评价'
                : '请先选择店铺',
            }}
          />
        </Card>
      )}

      <ReviewDetailDrawer
        open={drawerOpen}
        review={activeReview}
        shopPlatform={shopPlatform}
        onClose={onDrawerClose}
      />

      <SettingsModal
        open={settingsOpen}
        shopId={shopId}
        shopName={currentShop?.name}
        onClose={() => setSettingsOpen(false)}
      />
    </div>
  )
}

export default Reviews
