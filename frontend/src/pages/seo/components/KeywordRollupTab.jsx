import { useState, useEffect, useCallback } from 'react'
import {
  Card, Table, Space, Segmented, Input, InputNumber, Button, Tag,
  Drawer, Empty, Alert, Typography, Image, message, Select,
} from 'antd'
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import { getKeywordRollup, getKeywordRollupProducts } from '@/api/seo'

const { Text } = Typography

const KeywordRollupTab = ({ shops = [], shopId, onShopChange, onJumpToProduct }) => {
  const [days, setDays] = useState(30)
  const [sort, setSort] = useState('revenue_desc')
  const [keyword, setKeyword] = useState('')
  const [minOrders, setMinOrders] = useState(0)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [drawer, setDrawer] = useState({ open: false, keyword: '', items: [], loading: false })

  const fetchData = useCallback(async () => {
    if (!shopId) return
    setLoading(true)
    try {
      const res = await getKeywordRollup(shopId, {
        days, sort, keyword: keyword.trim(),
        min_orders: minOrders, limit: 200,
      })
      if (res.code === 0) setData(res.data)
      else message.error(res.msg || '拉取失败')
    } catch (e) {
      message.error(e?.response?.data?.msg || '网络错误')
    } finally {
      setLoading(false)
    }
  }, [shopId, days, sort, keyword, minOrders])

  useEffect(() => { fetchData() }, [fetchData])

  const handleDrillDown = async (row) => {
    setDrawer({ open: true, keyword: row.keyword, items: [], loading: true })
    try {
      const res = await getKeywordRollupProducts(shopId, {
        keyword: row.keyword, days, limit: 50,
      })
      if (res.code === 0) {
        setDrawer({ open: true, keyword: row.keyword, items: res.data?.items || [], loading: false })
      } else {
        message.error(res.msg || '下钻失败')
        setDrawer(prev => ({ ...prev, loading: false }))
      }
    } catch (e) {
      message.error(e?.response?.data?.msg || '网络错误')
      setDrawer(prev => ({ ...prev, loading: false }))
    }
  }

  const summary = data?.summary

  const columns = [
    {
      title: '关键词', dataIndex: 'keyword', key: 'keyword',
      render: (v, r) => (
        <Space direction="vertical" size={0}>
          <Text strong>{v}</Text>
          {r.product_count > 1 && (
            <Tag color="blue" style={{ fontSize: 11 }}>覆盖 {r.product_count} 个商品</Tag>
          )}
        </Space>
      ),
    },
    {
      title: '曝光', dataIndex: 'impressions', align: 'right', width: 100,
      render: v => (v || 0).toLocaleString(),
    },
    {
      title: '加购', dataIndex: 'add_to_cart', align: 'right', width: 80,
      render: v => (v || 0).toLocaleString(),
    },
    {
      title: '订单', dataIndex: 'orders', align: 'right', width: 80,
      render: v => v > 0 ? <Text strong style={{ color: '#52c41a' }}>{v}</Text> : (v || 0),
    },
    {
      title: '收入', dataIndex: 'revenue', align: 'right', width: 110,
      render: v => `¥${Number(v || 0).toFixed(2)}`,
    },
    {
      title: '操作', key: 'action', align: 'center', fixed: 'right', width: 130,
      render: (_, r) => (
        <Button size="small" type="link" onClick={() => handleDrillDown(r)}>
          看落到哪些商品
        </Button>
      ),
    },
  ]

  const drillColumns = [
    {
      title: '商品', key: 'product',
      render: (_, r) => (
        <Space>
          {r.image_url && (
            <Image
              src={r.image_url}
              width={44} height={44}
              style={{ borderRadius: 4, objectFit: 'cover' }}
              preview={false}
              fallback="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='44' height='44'%3E%3Crect fill='%23eee' width='44' height='44'/%3E%3C/svg%3E"
            />
          )}
          <Space direction="vertical" size={0}>
            <Text style={{ fontSize: 13, maxWidth: 320 }} ellipsis={{ tooltip: r.title }}>
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
      title: '曝光', dataIndex: 'impressions', align: 'right', width: 90,
      render: v => (v || 0).toLocaleString(),
    },
    { title: '加购', dataIndex: 'add_to_cart', align: 'right', width: 70 },
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
            productId: r.product_id, keyword: drawer.keyword,
          })}
        >
          去加进标题
        </Button>
      ),
    },
  ]

  return (
    <Card>
      <Alert
        type="info" showIcon
        style={{ marginBottom: 12 }}
        message="店级关键词 TOP —— 每一行 = 一个关键词，跨商品汇总贡献"
        description={(
          <div>
            <div>同一个词在多个商品下的曝光 / 订单 / 收入会合并成一行；点「看落到哪些商品」看这词具体靠哪几个商品撑起来。</div>
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
        <Text type="secondary">订单 ≥</Text>
        <InputNumber
          min={0} max={1000}
          value={minOrders}
          onChange={v => setMinOrders(v || 0)}
          style={{ width: 76 }}
        />
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
            columns={columns}
            dataSource={data?.items || []}
            loading={loading}
            size="small"
            scroll={{ x: 'max-content' }}
            pagination={{
              pageSize: 20, showSizeChanger: true,
              pageSizeOptions: [20, 50, 100],
              showTotal: (t) => `共 ${t} 个词`,
            }}
            locale={{ emptyText: <Empty description="当前条件下无数据" /> }}
          />
        </>
      )}

      <Drawer
        open={drawer.open}
        onClose={() => setDrawer({ open: false, keyword: '', items: [], loading: false })}
        title={(
          <span>
            关键词「<Text code>{drawer.keyword}</Text>」落到哪些商品
          </span>
        )}
        width={820}
      >
        <Alert
          type="info" showIcon
          style={{ marginBottom: 12 }}
          message={`近 ${days} 天该词共落在 ${drawer.items.length} 个商品上（按收入降序）。`}
        />
        <Table
          rowKey="product_id"
          columns={drillColumns}
          dataSource={drawer.items}
          loading={drawer.loading}
          size="small"
          pagination={false}
          locale={{ emptyText: <Empty description="该词暂无分商品数据" /> }}
        />
      </Drawer>
    </Card>
  )
}

export default KeywordRollupTab
