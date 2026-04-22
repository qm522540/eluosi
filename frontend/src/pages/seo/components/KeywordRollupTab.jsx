import { useState, useEffect, useCallback } from 'react'
import {
  Card, Table, Space, Segmented, Input, InputNumber, Button, Tag,
  Empty, Alert, Typography, Image, message, Select, Rate, Tooltip,
} from 'antd'
import { ReloadOutlined, SearchOutlined, DownOutlined, RightOutlined } from '@ant-design/icons'
import { getKeywordRollup, getKeywordRollupProducts } from '@/api/seo'

const { Text } = Typography

const KeywordRollupTab = ({ shops = [], shopId, onShopChange, onJumpToProduct }) => {
  const [days, setDays] = useState(30)
  const [sort, setSort] = useState('revenue_desc')
  const [keyword, setKeyword] = useState('')
  const [minOrders, setMinOrders] = useState(0)
  const [onlyWithOrders, setOnlyWithOrders] = useState(false)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)

  // 展开行 state: { [keyword]: { loading, items } }
  const [expanded, setExpanded] = useState({})
  const [expandedKeys, setExpandedKeys] = useState([])

  const fetchData = useCallback(async () => {
    if (!shopId) return
    setLoading(true)
    try {
      const res = await getKeywordRollup(shopId, {
        days, sort, keyword: keyword.trim(),
        min_orders: onlyWithOrders ? Math.max(1, minOrders) : minOrders,
        limit: 200,
      })
      if (res.code === 0) {
        setData(res.data)
        // 拉新数据时清空已展开 cache，避免看到陈旧数据
        setExpanded({})
        setExpandedKeys([])
      } else {
        message.error(res.msg || '拉取失败')
      }
    } catch (e) {
      message.error(e?.response?.data?.msg || '网络错误')
    } finally {
      setLoading(false)
    }
  }, [shopId, days, sort, keyword, minOrders, onlyWithOrders])

  useEffect(() => { fetchData() }, [fetchData])

  const loadProducts = async (kw) => {
    setExpanded(prev => ({ ...prev, [kw]: { loading: true, items: [] } }))
    try {
      const res = await getKeywordRollupProducts(shopId, { keyword: kw, days, limit: 50 })
      if (res.code === 0) {
        setExpanded(prev => ({ ...prev, [kw]: { loading: false, items: res.data?.items || [] } }))
      } else {
        message.error(res.msg || '下钻失败')
        setExpanded(prev => ({ ...prev, [kw]: { loading: false, items: [] } }))
      }
    } catch (e) {
      message.error(e?.response?.data?.msg || '网络错误')
      setExpanded(prev => ({ ...prev, [kw]: { loading: false, items: [] } }))
    }
  }

  const handleExpand = (expandedRow, record) => {
    const kw = record.keyword
    if (expandedRow) {
      setExpandedKeys(prev => [...prev, kw])
      if (!expanded[kw]) loadProducts(kw)
    } else {
      setExpandedKeys(prev => prev.filter(k => k !== kw))
    }
  }

  const summary = data?.summary

  const mainColumns = [
    {
      title: '关键词', dataIndex: 'keyword', key: 'keyword',
      render: (v) => <Text strong style={{ fontSize: 13 }}>{v}</Text>,
    },
    {
      title: (
        <Tooltip title="蓝=真给这么多商品带过搜索流量/订单；橙=「按商品看」把这词推荐加进的商品数（含类目扩散推断，未必真带过流量）">
          真实贡献 <Text type="secondary" style={{ fontSize: 11 }}>/ 推荐覆盖</Text>
        </Tooltip>
      ),
      key: 'coverage', align: 'center', width: 140,
      render: (_, r) => (
        <Space size={2}>
          <Tag color="blue" style={{ margin: 0, fontSize: 12 }}>
            {r.product_count} 商品
          </Tag>
          <Text type="secondary" style={{ fontSize: 11 }}>/</Text>
          <Tag
            color={r.candidate_row_count > r.product_count ? 'orange' : 'default'}
            style={{ margin: 0, fontSize: 12 }}
          >
            {r.candidate_row_count || r.product_count} 商品
          </Tag>
        </Space>
      ),
    },
    {
      title: '曝光', dataIndex: 'impressions', align: 'right', width: 90,
      render: v => (v || 0).toLocaleString(),
    },
    { title: '加购', dataIndex: 'add_to_cart', align: 'right', width: 70 },
    {
      title: '订单', dataIndex: 'orders', align: 'right', width: 80,
      render: v => v > 0 ? <Text strong style={{ color: '#52c41a' }}>{v}</Text> : (v || 0),
    },
    {
      title: '收入', dataIndex: 'revenue', align: 'right', width: 110,
      render: v => `¥${Number(v || 0).toFixed(2)}`,
    },
  ]

  const renderExpanded = (record) => {
    const kw = record.keyword
    const state = expanded[kw]
    if (!state) return null

    const subColumns = [
      {
        title: '商品', key: 'product',
        render: (_, r) => (
          <Space>
            {r.image_url && (
              <Image
                src={r.image_url}
                width={40} height={40}
                style={{ borderRadius: 4, objectFit: 'cover' }}
                preview={false}
                fallback="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='40' height='40'%3E%3Crect fill='%23eee' width='40' height='40'/%3E%3C/svg%3E"
              />
            )}
            <Space direction="vertical" size={0}>
              <Text style={{ fontSize: 12, maxWidth: 360 }} ellipsis={{ tooltip: r.title }}>
                {r.title || '(无标题)'}
              </Text>
              <Text type="secondary" style={{ fontSize: 11 }}>
                SKU {r.platform_sku_id || r.product_id}
              </Text>
            </Space>
          </Space>
        ),
      },
      {
        title: '评分', key: 'rating', width: 130, align: 'center',
        render: (_, r) => {
          if (r.rating == null) return <Text type="secondary" style={{ fontSize: 11 }}>-</Text>
          return (
            <Space direction="vertical" size={0} style={{ lineHeight: 1.2 }}>
              <Space size={4}>
                <Rate disabled value={r.rating} allowHalf style={{ fontSize: 11 }} />
                <Text strong style={{ fontSize: 11 }}>{Number(r.rating).toFixed(1)}</Text>
              </Space>
              <Text type="secondary" style={{ fontSize: 10 }}>
                {r.review_count || 0} 条评价
              </Text>
            </Space>
          )
        },
      },
      {
        title: '曝光', dataIndex: 'impressions', align: 'right', width: 80,
        render: v => (v || 0).toLocaleString(),
      },
      { title: '加购', dataIndex: 'add_to_cart', align: 'right', width: 60 },
      {
        title: '订单', dataIndex: 'orders', align: 'right', width: 70,
        render: v => v > 0 ? <Text strong style={{ color: '#52c41a' }}>{v}</Text> : (v || 0),
      },
      {
        title: '收入', dataIndex: 'revenue', align: 'right', width: 100,
        render: v => `¥${Number(v || 0).toFixed(2)}`,
      },
      {
        title: '操作', key: 'action', width: 110, align: 'center',
        render: (_, r) => (
          <Button
            size="small" type="link"
            onClick={() => onJumpToProduct && onJumpToProduct({
              productId: r.product_id, keyword: kw,
            })}
          >
            加进标题
          </Button>
        ),
      },
    ]

    return (
      <div style={{ padding: '8px 16px', background: '#fafafa' }}>
        <Text type="secondary" style={{ fontSize: 12, marginBottom: 8, display: 'block' }}>
          「<Text code>{kw}</Text>」真实落在以下商品（按收入降序）：
        </Text>
        <Table
          rowKey="product_id"
          columns={subColumns}
          dataSource={state.items}
          loading={state.loading}
          size="small"
          pagination={false}
          locale={{ emptyText: <Empty description="该词暂无商品分项" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
        />
      </div>
    )
  }

  return (
    <Card>
      <Alert
        type="info" showIcon
        style={{ marginBottom: 12 }}
        message="店级关键词 TOP —— 每行 = 一个关键词，点 ▶ 层叠展开看落到哪些商品"
        description={(
          <div>
            <div style={{ marginTop: 4 }}>
              <strong>「真实贡献 / 推荐覆盖」两个数字的含义：</strong>
            </div>
            <ul style={{ paddingLeft: 20, marginTop: 4, marginBottom: 4, lineHeight: 1.7 }}>
              <li>
                <Tag color="blue" style={{ marginRight: 4 }}>蓝</Tag>
                <strong>真实贡献商品数</strong>：这个词真给多少个商品带过搜索流量/订单（来自 product_search_queries 原始数据）
              </li>
              <li>
                <Tag color="orange" style={{ marginRight: 4 }}>橙</Tag>
                <strong>推荐覆盖商品数</strong>：「按商品看」Tab 把这词推荐加进多少个商品的标题（含「类目扩散」机制，给没带过流量的同类目商品也推荐）
              </li>
            </ul>
            <div style={{ marginTop: 4, color: '#888', fontSize: 12 }}>
              数据来自平台自然搜索（organic 源）。WB 需 Jam 订阅 / Ozon 需 Premium 订阅。
            </div>
          </div>
        )}
      />

      <Space wrap style={{ marginBottom: 12 }}>
        <Text type="secondary">店铺：</Text>
        <Select
          style={{ width: 200 }}
          value={shopId}
          onChange={v => onShopChange && onShopChange(v)}
          options={shops.map(s => ({ label: `${s.name} (${s.platform})`, value: s.id }))}
        />
        <Text type="secondary">窗口：</Text>
        <Segmented
          value={days}
          onChange={setDays}
          options={[
            { label: '7 天', value: 7 },
            { label: '14 天', value: 14 },
            { label: '30 天', value: 30 },
            { label: '60 天', value: 60 },
          ]}
        />
        <Text type="secondary">排序：</Text>
        <Segmented
          value={sort}
          onChange={setSort}
          options={[
            { label: '收入 ↓', value: 'revenue_desc' },
            { label: '订单 ↓', value: 'orders_desc' },
            { label: '曝光 ↓', value: 'impressions_desc' },
            { label: '加购 ↓', value: 'cart_desc' },
          ]}
        />
        <Input
          placeholder="关键词筛选"
          prefix={<SearchOutlined />}
          allowClear
          value={keyword}
          onChange={e => setKeyword(e.target.value)}
          onPressEnter={fetchData}
          style={{ width: 180 }}
        />
        <Button
          size="small"
          type={onlyWithOrders ? 'primary' : 'default'}
          onClick={() => setOnlyWithOrders(v => !v)}
        >
          仅带订单 {onlyWithOrders ? '✓' : ''}
        </Button>
        {!onlyWithOrders && (
          <>
            <Text type="secondary">订单 ≥</Text>
            <InputNumber
              min={0} max={1000}
              value={minOrders}
              onChange={v => setMinOrders(v || 0)}
              style={{ width: 76 }}
            />
          </>
        )}
        <Button icon={<ReloadOutlined />} onClick={fetchData}>刷新</Button>
      </Space>

      {data?.data_status === 'not_ready' ? (
        <Alert
          type="warning" showIcon
          message="该店铺搜索词数据尚未就绪"
          description={data?.hint || '暂无自然搜索词数据。'}
        />
      ) : (
        <>
          {summary && (
            <div style={{
              marginBottom: 12, padding: '8px 12px',
              background: '#f6ffed', border: '1px solid #b7eb8f',
              borderRadius: 4, fontSize: 13,
            }}>
              <Text>近 {data?.days} 天汇总：</Text>
              <Text strong style={{ marginLeft: 10 }}>{summary.kw_count}</Text>
              <Text type="secondary"> 个词 · </Text>
              <Text strong>{summary.total_impressions.toLocaleString()}</Text>
              <Text type="secondary"> 总曝光 · </Text>
              <Text strong style={{ color: '#52c41a' }}>{summary.total_orders}</Text>
              <Text type="secondary"> 总订单 · </Text>
              <Text strong>¥{summary.total_revenue.toFixed(2)}</Text>
              <Text type="secondary"> 总收入</Text>
            </div>
          )}

          <Table
            rowKey="keyword"
            columns={mainColumns}
            dataSource={data?.items || []}
            loading={loading}
            size="small"
            expandable={{
              expandedRowKeys: expandedKeys,
              onExpand: handleExpand,
              expandedRowRender: renderExpanded,
              expandIcon: ({ expanded: isExpanded, onExpand, record }) => (
                isExpanded
                  ? <DownOutlined onClick={e => onExpand(record, e)} style={{ cursor: 'pointer' }} />
                  : <RightOutlined onClick={e => onExpand(record, e)} style={{ cursor: 'pointer' }} />
              ),
            }}
            pagination={{
              pageSize: 20, showSizeChanger: true,
              pageSizeOptions: [20, 50, 100],
              showTotal: (t) => `共 ${t} 个词`,
            }}
            locale={{ emptyText: <Empty description="当前条件下无数据" /> }}
          />
        </>
      )}
    </Card>
  )
}

export default KeywordRollupTab
