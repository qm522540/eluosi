import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Table, Tag, Tooltip, Button, Drawer, Space, Typography, Avatar, message } from 'antd'
import { ArrowUpOutlined, ArrowDownOutlined, MinusOutlined, WarningOutlined, RobotOutlined } from '@ant-design/icons'
import { getKeywordTrackingSkus } from '@/api/seo'

const { Text, Paragraph } = Typography

const TREND_META = {
  new:    { color: 'green',   label: '新增',   icon: <ArrowUpOutlined /> },
  up:     { color: 'cyan',    label: '上升',   icon: <ArrowUpOutlined /> },
  stable: { color: 'default', label: '持平',   icon: <MinusOutlined /> },
  down:   { color: 'orange',  label: '下降',   icon: <ArrowDownOutlined /> },
  vanish: { color: 'red',     label: '消失',   icon: <ArrowDownOutlined /> },
  idle:   { color: 'default', label: '无曝光', icon: <MinusOutlined /> },
}

const ALERT_META = {
  drop:        { color: 'orange', label: '曝光跌幅 ≥ 30%',        hint: '本期曝光相对上期下降超过 30%，考虑排查商品上架/库存/价格变化' },
  vanish:      { color: 'red',    label: '曝光消失',               hint: '上期曝光 ≥ 50 但本期为 0，紧急核查商品是否下架或被平台屏蔽' },
  orders_drop: { color: 'volcano',label: '订单归零',               hint: '上期有订单但本期无，可能流量来了转化没跟上' },
}

const DeltaText = ({ pct, trend }) => {
  if (pct === null || pct === undefined) {
    if (trend === 'new') return <Tag color="green">新词</Tag>
    if (trend === 'idle') return <Text type="secondary">—</Text>
    return <Text type="secondary">—</Text>
  }
  const color = pct >= 20 ? '#3f8600' : pct <= -20 ? '#cf1322' : '#666'
  const sign = pct > 0 ? '+' : ''
  return <span style={{ color, fontWeight: pct >= 20 || pct <= -20 ? 600 : 400 }}>{sign}{pct}%</span>
}

const TrackingTable = ({ shopId, data, loading, pagination, onPaginationChange, hasPositionData, positionHint }) => {
  const navigate = useNavigate()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerLoading, setDrawerLoading] = useState(false)
  const [drawerQuery, setDrawerQuery] = useState(null)
  const [drawerData, setDrawerData] = useState(null)

  const openDrawer = async (query_text) => {
    setDrawerOpen(true)
    setDrawerQuery(query_text)
    setDrawerLoading(true)
    try {
      const res = await getKeywordTrackingSkus(shopId, { query_text, date_range: 7, limit: 10 })
      if (res.code === 0) setDrawerData(res.data)
      else message.error(res.msg || '拉取失败')
    } catch (e) {
      message.error(e?.response?.data?.msg || '网络错误')
    } finally {
      setDrawerLoading(false)
    }
  }

  const closeDrawer = () => {
    setDrawerOpen(false)
    setDrawerData(null)
    setDrawerQuery(null)
  }

  const gotoOptimize = (productId) => {
    if (!productId) {
      message.warning('该 SKU 未绑定商品，无法跳转优化页')
      return
    }
    navigate(`/seo/optimize?shopId=${shopId}&productId=${productId}`)
  }

  const columns = [
    {
      title: '核心词',
      dataIndex: 'query_text',
      width: 260,
      render: (v, r) => (
        <Space direction="vertical" size={0}>
          <Text style={{ fontSize: 13, fontWeight: 500 }}>{v}</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>涉及 {r.skus_involved} 商品</Text>
        </Space>
      ),
    },
    {
      title: '本期曝光',
      dataIndex: 'impressions_cur',
      width: 95,
      align: 'right',
      sorter: (a, b) => a.impressions_cur - b.impressions_cur,
      render: (v, r) => (
        <Space direction="vertical" size={0}>
          <Text strong>{v.toLocaleString()}</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>上期 {r.impressions_prev.toLocaleString()}</Text>
        </Space>
      ),
    },
    {
      title: '环比',
      dataIndex: 'impressions_delta_pct',
      width: 85,
      align: 'right',
      render: (pct, r) => <DeltaText pct={pct} trend={r.trend} />,
    },
    {
      title: '订单',
      dataIndex: 'orders_cur',
      width: 80,
      align: 'right',
      render: (v, r) => (
        <Space direction="vertical" size={0}>
          <Text strong style={{ color: v > 0 ? '#52c41a' : '#999' }}>{v}</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>上期 {r.orders_prev}</Text>
        </Space>
      ),
    },
    {
      title: '加购',
      dataIndex: 'cart_cur',
      width: 70,
      align: 'right',
      render: (v) => v > 0 ? <Text>{v}</Text> : <Text type="secondary">—</Text>,
    },
    {
      title: '营收',
      dataIndex: 'revenue_cur',
      width: 95,
      align: 'right',
      render: (v) => v > 0 ? <Text>₽{Number(v).toFixed(0)}</Text> : <Text type="secondary">—</Text>,
    },
    {
      title: '排名',
      dataIndex: 'avg_position',
      width: 70,
      align: 'right',
      render: (v) => {
        if (v === null || v === undefined) {
          return <Tooltip title={positionHint || '无排名数据'}><Text type="secondary">—</Text></Tooltip>
        }
        return <Text>{v}</Text>
      },
    },
    {
      title: '趋势',
      dataIndex: 'trend',
      width: 80,
      render: (t) => {
        const m = TREND_META[t] || TREND_META.idle
        return <Tag color={m.color} icon={m.icon}>{m.label}</Tag>
      },
    },
    {
      title: '预警',
      dataIndex: 'alert',
      width: 130,
      render: (a) => {
        if (!a) return <Text type="secondary" style={{ fontSize: 11 }}>—</Text>
        const m = ALERT_META[a]
        return (
          <Tooltip title={m?.hint}>
            <Tag color={m?.color || 'default'} icon={<WarningOutlined />}>{m?.label || a}</Tag>
          </Tooltip>
        )
      },
    },
    {
      title: '操作',
      key: 'op',
      width: 80,
      render: (_, r) => <Button size="small" type="link" onClick={() => openDrawer(r.query_text)}>下钻</Button>,
    },
  ]

  return (
    <>
      <Table
        rowKey="query_text"
        size="small"
        loading={loading}
        dataSource={data || []}
        columns={columns}
        pagination={pagination}
        onChange={onPaginationChange}
        scroll={{ x: 1150 }}
      />

      <Drawer
        title={drawerQuery ? `词下钻: "${drawerQuery}"` : '词下钻'}
        open={drawerOpen}
        onClose={closeDrawer}
        width={720}
      >
        {drawerLoading ? (
          <Text type="secondary">加载中…</Text>
        ) : drawerData ? (
          <>
            <Paragraph type="secondary" style={{ fontSize: 12 }}>
              时间段 {drawerData.period?.start} ~ {drawerData.period?.end}，按本期曝光排序。
              点「AI 优化标题」直接跳去优化页处理该商品。
            </Paragraph>
            <Table
              size="small"
              rowKey={(r) => `${r.product_id}_${r.platform_sku_id}`}
              dataSource={drawerData.items || []}
              pagination={false}
              columns={[
                {
                  title: '商品',
                  render: (_, r) => (
                    <Space>
                      {r.image_url && <Avatar shape="square" src={r.image_url} size={40} />}
                      <Space direction="vertical" size={0}>
                        <Text style={{ fontSize: 12 }}>{r.product_name || r.platform_sku_id}</Text>
                        <Text type="secondary" style={{ fontSize: 11 }}>{r.title_ru || '（无俄语标题）'}</Text>
                      </Space>
                    </Space>
                  ),
                },
                { title: '曝光', dataIndex: 'impressions', width: 70, align: 'right' },
                { title: '订单', dataIndex: 'orders', width: 60, align: 'right',
                  render: (v) => <Text style={{ color: v > 0 ? '#52c41a' : '#999' }}>{v}</Text> },
                { title: '营收', dataIndex: 'revenue', width: 80, align: 'right',
                  render: (v) => v > 0 ? `₽${Number(v).toFixed(0)}` : '—' },
                {
                  title: '操作', key: 'op', width: 110,
                  render: (_, r) => (
                    <Button size="small" type="link" icon={<RobotOutlined />}
                      onClick={() => gotoOptimize(r.product_id)}>AI 优化标题</Button>
                  ),
                },
              ]}
            />
          </>
        ) : (
          <Text type="secondary">无数据</Text>
        )}
      </Drawer>
    </>
  )
}

export default TrackingTable
