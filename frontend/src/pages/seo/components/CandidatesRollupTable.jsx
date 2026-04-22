import { useState, useEffect, useCallback } from 'react'
import {
  Card, Table, Space, Segmented, Input, Button, Tag, Badge,
  Empty, Alert, Typography, Image, message, Select, Rate, Tooltip, Switch,
} from 'antd'
import {
  ReloadOutlined, SearchOutlined, DownOutlined, RightOutlined,
  TagOutlined, CheckCircleFilled, CloseCircleFilled,
} from '@ant-design/icons'
import {
  getCandidatesRollup, getCandidatesRollupProducts,
} from '@/api/seo'

const { Text } = Typography

const SOURCE_OPTIONS = [
  { label: '全部', value: 'all' },
  { label: '带订单', value: 'with_orders' },
  { label: '付费·本商品', value: 'paid_self' },
  { label: '付费·类目', value: 'paid_category' },
  { label: '自然·本商品', value: 'organic_self' },
  { label: '自然·类目', value: 'organic_category' },
]

const CandidatesRollupTable = ({
  shopId,
  onAdoptProduct,   // (productId, keyword) => 父层处理"加进标题"（切模式到按商品看 + 填 productFilter + 拉 AI Modal 候选）
}) => {
  const [source, setSource] = useState('all')
  const [status, setStatus] = useState('pending')
  const [keyword, setKeyword] = useState('')
  const [hideCovered, setHideCovered] = useState(true)
  const [sort, setSort] = useState('score_desc')

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState({})
  const [expandedKeys, setExpandedKeys] = useState([])

  const fetchData = useCallback(async () => {
    if (!shopId) return
    setLoading(true)
    try {
      const res = await getCandidatesRollup(shopId, {
        source, status, keyword: keyword.trim(),
        hide_covered: hideCovered, sort, limit: 200,
      })
      if (res.code === 0) {
        setData(res.data)
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
  }, [shopId, source, status, keyword, hideCovered, sort])

  useEffect(() => { fetchData() }, [fetchData])

  const loadProducts = async (kw) => {
    setExpanded(prev => ({ ...prev, [kw]: { loading: true, items: [] } }))
    try {
      const res = await getCandidatesRollupProducts(shopId, { keyword: kw, status, limit: 100 })
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

  const handleExpand = (isExpanded, record) => {
    const kw = record.keyword
    if (isExpanded) {
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
      render: (v, r) => (
        <Space direction="vertical" size={2}>
          <Text strong style={{ fontSize: 13 }}>{v}</Text>
          <Space size={4} wrap>
            {r.has_paid && <Tag color="purple" style={{ margin: 0, fontSize: 10 }}>付费</Tag>}
            {r.has_organic && <Tag color="cyan" style={{ margin: 0, fontSize: 10 }}>自然</Tag>}
          </Space>
        </Space>
      ),
    },
    {
      title: (
        <Tooltip title="蓝=真给这么多商品带过订单；橙=这词被推荐加进多少商品的标题（含类目扩散推断）">
          真实贡献 <Text type="secondary" style={{ fontSize: 11 }}>/ 推荐覆盖</Text>
        </Tooltip>
      ),
      key: 'coverage', align: 'center', width: 140,
      render: (_, r) => (
        <Space size={2}>
          <Tag color="blue" style={{ margin: 0, fontSize: 12 }}>
            {r.self_product_count} 商品
          </Tag>
          <Text type="secondary" style={{ fontSize: 11 }}>/</Text>
          <Tag
            color={r.product_count > r.self_product_count ? 'orange' : 'default'}
            style={{ margin: 0, fontSize: 12 }}
          >
            {r.product_count} 商品
          </Tag>
        </Space>
      ),
    },
    {
      title: (
        <Tooltip title="只对真带过订单的商品求和（self scope 真数据），不算类目扩散继承的虚数">
          订单
        </Tooltip>
      ),
      dataIndex: 'total_orders', align: 'right', width: 80,
      render: v => v > 0 ? <Text strong style={{ color: '#52c41a' }}>{v}</Text> : (v || 0),
    },
    { title: '曝光', dataIndex: 'total_impressions', align: 'right', width: 90,
      render: v => (v || 0).toLocaleString() },
    { title: '加购', dataIndex: 'total_add_to_cart', align: 'right', width: 70 },
    {
      title: (
        <Tooltip title="系统打分：来源数×2 + ROAS + log(订单+1)×2 + log(曝光+1) + log(自然订单+1)×2">
          优先级
        </Tooltip>
      ),
      dataIndex: 'max_score', align: 'center', width: 80,
      render: v => (
        <Tag color={v >= 8 ? 'red' : v >= 5 ? 'orange' : v >= 3 ? 'gold' : 'default'}
             style={{ fontSize: 11, minWidth: 36, textAlign: 'center', margin: 0 }}>
          {(v || 0).toFixed(1)}
        </Tag>
      ),
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
              <Text style={{ fontSize: 12, maxWidth: 280 }} ellipsis={{ tooltip: r.title }}>
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
        title: '评分', key: 'rating', width: 110, align: 'center',
        render: (_, r) => {
          if (r.rating == null) return <Text type="secondary" style={{ fontSize: 11 }}>-</Text>
          return (
            <Space direction="vertical" size={0} style={{ lineHeight: 1.2 }}>
              <Space size={2}>
                <Rate disabled value={r.rating} allowHalf style={{ fontSize: 10 }} />
                <Text strong style={{ fontSize: 11 }}>{Number(r.rating).toFixed(1)}</Text>
              </Space>
              <Text type="secondary" style={{ fontSize: 10 }}>{r.review_count || 0} 评价</Text>
            </Space>
          )
        },
      },
      {
        title: '实证表现', key: 'evidence', width: 170,
        render: (_, r) => {
          if (!r.has_self) {
            return (
              <Tooltip title="本商品尚未被用户用这词搜到过；系统基于同类目其他商品的成交数据推荐加进标题试水">
                <Tag color="default" style={{ fontSize: 11, cursor: 'help' }}>
                  暂无实证 · 系统推荐
                </Tag>
              </Tooltip>
            )
          }
          const ord = (r.paid_orders || 0) + (r.organic_orders || 0)
          const imp = r.organic_impressions || 0
          return (
            <div style={{ fontSize: 12, lineHeight: 1.4 }}>
              {ord > 0 ? (
                <div><Text strong style={{ color: '#cf1322' }}>订单 {ord}</Text> <Text type="secondary">曝光 {imp}</Text></div>
              ) : (
                <div><Text>曝光 <strong>{imp}</strong></Text></div>
              )}
              {r.paid_roas != null && (
                <div style={{ color: '#888', fontSize: 11 }}>ROAS {r.paid_roas.toFixed(2)}</div>
              )}
            </div>
          )
        },
      },
      {
        title: '覆盖', key: 'cover', width: 80, align: 'center',
        render: (_, r) => (
          <Space size={6}>
            <Tooltip title={`标题${r.in_title ? '已含' : '未含'}该词`}>
              {r.in_title
                ? <CheckCircleFilled style={{ color: '#52c41a' }} />
                : <CloseCircleFilled style={{ color: '#d9d9d9' }} />}
            </Tooltip>
            <Tooltip title={`属性${r.in_attrs ? '已含' : '未含'}该词`}>
              {r.in_attrs
                ? <CheckCircleFilled style={{ color: '#52c41a' }} />
                : <CloseCircleFilled style={{ color: '#d9d9d9' }} />}
            </Tooltip>
          </Space>
        ),
      },
      {
        title: '优先级', dataIndex: 'score', align: 'center', width: 80,
        render: v => (
          <Tag color={v >= 8 ? 'red' : v >= 5 ? 'orange' : 'default'}
               style={{ fontSize: 11, margin: 0 }}>
            {Number(v || 0).toFixed(1)}
          </Tag>
        ),
      },
      {
        title: '状态', dataIndex: 'status', align: 'center', width: 80,
        render: s => {
          const map = {
            pending:  <Badge status="processing" text="待处理" />,
            adopted:  <Badge status="success" text="已加入" />,
            ignored:  <Badge status="default" text="已忽略" />,
          }
          return map[s] || s
        },
      },
      {
        title: '操作', key: 'action', width: 120, align: 'center',
        render: (_, r) => (
          r.status === 'pending' ? (
            <Button
              size="small" type="link" icon={<TagOutlined />}
              onClick={() => onAdoptProduct && onAdoptProduct(r.product_id, kw)}
            >
              给此商品改标题
            </Button>
          ) : r.status === 'adopted' ? (
            <Text type="success" style={{ fontSize: 11 }}>✓ 已加入</Text>
          ) : (
            <Text type="secondary" style={{ fontSize: 11 }}>已忽略</Text>
          )
        ),
      },
    ]

    return (
      <div style={{ padding: '8px 16px', background: '#fafafa' }}>
        <Text type="secondary" style={{ fontSize: 12, marginBottom: 8, display: 'block' }}>
          「<Text code>{kw}</Text>」候选商品（<Text strong>真实贡献商品排前</Text>，下方是类目推断推荐）：
        </Text>
        <Table
          rowKey="candidate_id"
          columns={subColumns}
          dataSource={state.items}
          loading={state.loading}
          size="small"
          pagination={false}
          locale={{ emptyText: <Empty description="暂无商品" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
        />
      </div>
    )
  }

  return (
    <div>
      <Alert
        type="info" showIcon
        style={{ marginBottom: 12 }}
        message="按商品看 · 关键词聚合视图 —— 每行 = 一个关键词，点 ▶ 展开看推荐加进哪些商品"
        description={(
          <div style={{ fontSize: 12 }}>
            <div>订单/曝光/加购只对<strong>真给该商品带过流量</strong>的 self scope 求和，不再重复计继承的类目扩散数字。</div>
            <div style={{ color: '#888', marginTop: 4 }}>
              展开行里点「给此商品改标题」会跳到单商品候选视图，能勾选多个词调 AI 生成新标题。
            </div>
          </div>
        )}
      />

      <Space wrap style={{ marginBottom: 12 }}>
        <Text type="secondary">数据源：</Text>
        <Select
          style={{ width: 160 }}
          value={source}
          onChange={setSource}
          options={SOURCE_OPTIONS}
        />
        <Text type="secondary">状态：</Text>
        <Segmented
          value={status}
          onChange={setStatus}
          options={[
            { label: '待处理', value: 'pending' },
            { label: '已加入', value: 'adopted' },
            { label: '已忽略', value: 'ignored' },
          ]}
        />
        <Text type="secondary">排序：</Text>
        <Segmented
          value={sort}
          onChange={setSort}
          options={[
            { label: '优先级 ↓', value: 'score_desc' },
            { label: '订单 ↓', value: 'orders_desc' },
            { label: '曝光 ↓', value: 'impr_desc' },
            { label: '覆盖商品 ↓', value: 'products_desc' },
          ]}
        />
        <Input
          placeholder="关键词筛"
          prefix={<SearchOutlined />}
          allowClear
          value={keyword}
          onChange={e => setKeyword(e.target.value)}
          onPressEnter={fetchData}
          style={{ width: 160 }}
        />
        <Text type="secondary">隐藏已覆盖：</Text>
        <Switch checked={hideCovered} onChange={setHideCovered} />
        <Button icon={<ReloadOutlined />} onClick={fetchData}>刷新</Button>
      </Space>

      {summary && (
        <div style={{
          marginBottom: 12, padding: '8px 12px',
          background: '#fff7e6', border: '1px solid #ffd591',
          borderRadius: 4, fontSize: 13,
        }}>
          <Text strong>{summary.kw_count}</Text> <Text type="secondary"> 个候选词 · </Text>
          <Text strong style={{ color: '#1677ff' }}>{summary.with_self_kw}</Text>
          <Text type="secondary"> 个有真实订单 · </Text>
          <Text strong style={{ color: '#52c41a' }}>{summary.total_orders}</Text>
          <Text type="secondary"> 总订单（真实） · </Text>
          <Text strong>{summary.total_impressions.toLocaleString()}</Text>
          <Text type="secondary"> 总曝光（真实）</Text>
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
        locale={{ emptyText: <Empty description="当前条件下无候选词" /> }}
      />
    </div>
  )
}

export default CandidatesRollupTable
