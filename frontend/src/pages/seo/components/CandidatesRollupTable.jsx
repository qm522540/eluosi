import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  Card, Table, Space, Segmented, Input, Button, Tag, Badge, Modal,
  Empty, Alert, Typography, Image, message, Select, Rate, Tooltip, Switch, List,
} from 'antd'
import {
  ReloadOutlined, SearchOutlined, DownOutlined, RightOutlined,
  TagOutlined, CheckCircleFilled, CloseCircleFilled, InfoCircleOutlined,
} from '@ant-design/icons'
import {
  getCandidatesRollup, getCandidatesRollupProducts,
  getCandidatesRollupCategoryEvidence,
} from '@/api/seo'

const { Text } = Typography

const SOURCE_OPTIONS = [
  { label: '带订单', value: 'with_orders' },
  { label: '付费·本商品', value: 'paid_self' },
  { label: '付费·类目', value: 'paid_category' },
  { label: '自然·本商品', value: 'organic_self' },
  { label: '自然·类目', value: 'organic_category' },
]

// 合并多店铺响应：按 keyword SUM 所有字段
const mergeRollup = (responses) => {
  const map = new Map()
  let totalImpressions = 0, totalOrders = 0
  responses.forEach(data => {
    if (!data) return
    const items = data?.items || []
    items.forEach(it => {
      const key = it.keyword.toLowerCase()
      const cur = map.get(key) || {
        keyword: it.keyword,
        product_count: 0, self_product_count: 0,
        total_orders: 0, total_impressions: 0, total_add_to_cart: 0,
        max_score: 0, has_paid: false, has_organic: false,
      }
      cur.product_count += it.product_count
      cur.self_product_count += it.self_product_count
      cur.total_orders += it.total_orders
      cur.total_impressions += it.total_impressions
      cur.total_add_to_cart += it.total_add_to_cart
      cur.max_score = Math.max(cur.max_score, it.max_score || 0)
      cur.has_paid = cur.has_paid || it.has_paid
      cur.has_organic = cur.has_organic || it.has_organic
      map.set(key, cur)
    })
    if (data?.summary) {
      totalImpressions += data.summary.total_impressions || 0
      totalOrders += data.summary.total_orders || 0
    }
  })
  return {
    items: Array.from(map.values()),
    summary: {
      kw_count: map.size,
      with_self_kw: Array.from(map.values()).filter(x => x.self_product_count > 0).length,
      total_orders: totalOrders,
      total_impressions: totalImpressions,
    },
  }
}

const sortItems = (items, sort) => {
  const arr = [...items]
  const cmp = {
    score_desc:    (a, b) => (b.max_score || 0) - (a.max_score || 0) || (b.total_orders - a.total_orders),
    orders_desc:   (a, b) => (b.total_orders - a.total_orders) || (b.max_score || 0) - (a.max_score || 0),
    impr_desc:     (a, b) => b.total_impressions - a.total_impressions,
    products_desc: (a, b) => b.product_count - a.product_count || b.total_orders - a.total_orders,
  }[sort] || (() => 0)
  return arr.sort(cmp)
}

const CandidatesRollupTable = ({
  shops = [],
  defaultShopId,
  onAdoptProduct,   // (shopId, productId, keyword) => 父层切单商品模式
}) => {
  // 多选店铺；默认取传入的主 shop
  const [shopIds, setShopIds] = useState(defaultShopId ? [defaultShopId] : [])
  const [sources, setSources] = useState([])  // 多选数据源，空=全部
  const [status, setStatus] = useState('pending')
  const [keyword, setKeyword] = useState('')
  const [hideCovered, setHideCovered] = useState(true)
  const [sort, setSort] = useState('score_desc')

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState({})
  const [expandedKeys, setExpandedKeys] = useState([])
  // 推荐理由 Modal：点"0 曝光·类目推断"行的 Tag 弹出 Top 5 真实命中商品
  const [evidenceModal, setEvidenceModal] = useState({ open: false, loading: false, keyword: '', evidence: null, items: [], shopId: null })

  const openEvidenceModal = useCallback(async (keyword, evidence, shopId) => {
    if (!evidence || !evidence.cat_id) return
    setEvidenceModal({ open: true, loading: true, keyword, evidence, items: [], shopId })
    try {
      const r = await getCandidatesRollupCategoryEvidence(shopId, {
        keyword, category_id: evidence.cat_id, limit: 5,
      })
      setEvidenceModal(s => ({ ...s, loading: false, items: r.data?.items || [] }))
    } catch (err) {
      setEvidenceModal(s => ({ ...s, loading: false }))
      message.error('加载证据失败：' + (err.response?.data?.msg || err.message))
    }
  }, [])

  // defaultShopId 变化时（父层切了主店铺）同步多选默认
  useEffect(() => {
    if (defaultShopId && shopIds.length === 0) {
      setShopIds([defaultShopId])
    }
  }, [defaultShopId])  // eslint-disable-line react-hooks/exhaustive-deps

  const sourceParam = useMemo(() => sources.join(',') || 'all', [sources])

  const fetchData = useCallback(async () => {
    if (!shopIds.length) { setData(null); return }
    setLoading(true)
    try {
      const results = await Promise.all(
        shopIds.map(sid => getCandidatesRollup(sid, {
          source: sourceParam, status, keyword: keyword.trim(),
          hide_covered: hideCovered, sort, limit: 500,
        }).catch(() => null))
      )
      const valid = results.filter(r => r && r.code === 0).map(r => r.data)
      const merged = mergeRollup(valid)
      merged.items = sortItems(merged.items, sort)
      setData(merged)
      setExpanded({})
      setExpandedKeys([])
    } catch (e) {
      message.error('网络错误')
    } finally {
      setLoading(false)
    }
  }, [shopIds, sourceParam, status, keyword, hideCovered, sort])

  useEffect(() => { fetchData() }, [fetchData])

  const loadProducts = async (kw) => {
    setExpanded(prev => ({ ...prev, [kw]: { loading: true, items: [] } }))
    try {
      const results = await Promise.all(
        shopIds.map(sid => getCandidatesRollupProducts(sid, {
          keyword: kw, status, limit: 100,
        }).catch(() => null))
      )
      const allItems = []
      results.forEach(r => {
        if (r && r.code === 0) allItems.push(...(r.data?.items || []))
      })
      // 按 has_self 优先 + score 降序
      allItems.sort((a, b) => {
        if (a.has_self !== b.has_self) return a.has_self ? -1 : 1
        return (b.score || 0) - (a.score || 0)
      })
      setExpanded(prev => ({ ...prev, [kw]: { loading: false, items: allItems } }))
    } catch (e) {
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
        <Tooltip title="蓝=真给这么多商品带过订单/曝光；橙=这词被推荐加进多少商品的标题（含类目扩散推断）">
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
      title: <Tooltip title="只对真带过订单的 self scope 行求和">订单</Tooltip>,
      dataIndex: 'total_orders', align: 'right', width: 80,
      render: v => v > 0 ? <Text strong style={{ color: '#52c41a' }}>{v}</Text> : (v || 0),
    },
    { title: '曝光', dataIndex: 'total_impressions', align: 'right', width: 90,
      render: v => (v || 0).toLocaleString() },
    { title: '加购', dataIndex: 'total_add_to_cart', align: 'right', width: 70 },
    {
      title: <Tooltip title="系统打分：来源数×2 + ROAS + log(订单+1)×2 + log(曝光+1) + log(自然订单+1)×2">优先级</Tooltip>,
      dataIndex: 'max_score', align: 'center', width: 80,
      render: v => (
        <Tag color={v >= 8 ? 'red' : v >= 5 ? 'orange' : v >= 3 ? 'gold' : 'default'}
             style={{ fontSize: 11, minWidth: 36, textAlign: 'center', margin: 0 }}>
          {(v || 0).toFixed(1)}
        </Tag>
      ),
    },
  ]

  const shopNameMap = useMemo(() => {
    const m = {}
    shops.forEach(s => { m[s.id] = s.name })
    return m
  }, [shops])

  const renderExpanded = (record) => {
    const kw = record.keyword
    const state = expanded[kw]
    if (!state) return null

    const subColumns = [
      {
        title: '店铺', key: 'shop', width: 100,
        render: (_, r) => <Tag color="geekblue" style={{ fontSize: 11 }}>{shopNameMap[r.shop_id] || `shop#${r.shop_id}`}</Tag>,
      },
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
              <Text style={{ fontSize: 12, maxWidth: 260 }} ellipsis={{ tooltip: r.title }}>
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
        title: '实证表现', key: 'evidence', width: 220,
        render: (_, r) => {
          if (!r.has_self) {
            const ev = r.category_evidence
            const catName = ev?.cat_name_ru || ev?.cat_name || '同类目'
            const pv  = ev?.products_verified || 0
            const ord = ev?.total_orders || 0
            const imp = ev?.total_impressions || 0
            const shopIdForEv = r.shop_id || shopIds[0] || defaultShopId
            if (!ev || pv === 0) {
              return (
                <Tooltip title="本商品在此词上 0 曝光；类目层面也没有 product_search_queries 证据（可能 seo_keyword_candidates 表有旧数据、或最近刚触发过推断）">
                  <Tag color="default" style={{ fontSize: 11, cursor: 'help' }}>0 曝光 · 系统推荐加词</Tag>
                </Tooltip>
              )
            }
            const summary = ord > 0
              ? `${pv} 款验证 · ${ord} 单 · ${imp.toLocaleString()} 曝光`
              : `${pv} 款验证 · ${imp.toLocaleString()} 曝光`
            return (
              <Tooltip
                overlayStyle={{ maxWidth: 360 }}
                title={(
                  <div style={{ lineHeight: 1.6 }}>
                    <div><strong>推荐理由（点 Tag 看详情）</strong></div>
                    <div style={{ marginTop: 4 }}>同类目 <Text strong style={{ color: '#ffd591' }}>{catName}</Text> 里有 <Text strong style={{ color: '#ffd591' }}>{pv}</Text> 款商品真实搜中此词，产生 <Text strong style={{ color: '#ffd591' }}>{imp.toLocaleString()}</Text> 曝光{ord > 0 ? ` / ${ord} 订单` : ''}</div>
                    <div style={{ marginTop: 6, color: '#ffe58f' }}>
                      系统认为同类目商品都适合加这词 → 把词加进本商品标题/属性 → 下次搜此词可能触发展示
                    </div>
                  </div>
                )}
              >
                <Tag
                  color="gold"
                  icon={<InfoCircleOutlined />}
                  style={{ fontSize: 11, cursor: 'pointer', marginRight: 0 }}
                  onClick={(e) => {
                    e.stopPropagation()
                    openEvidenceModal(kw, ev, shopIdForEv)
                  }}
                >
                  {summary}
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
              onClick={() => onAdoptProduct && onAdoptProduct(r.shop_id, r.product_id, kw)}
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
          「<Text code>{kw}</Text>」候选商品（<Text strong>真实贡献排前</Text>，类目推断排后）：
        </Text>
        <Table
          rowKey={(r) => `${r.shop_id}-${r.candidate_id}`}
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

  const shopOptions = shops.map(s => ({
    label: `${s.name} (${s.platform})`,
    value: s.id,
  }))

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
              多选店铺时跨店合并（同一关键词的真数据求和）；多选数据源时取并集。
            </div>
          </div>
        )}
      />

      <Space wrap style={{ marginBottom: 8 }}>
        <Text type="secondary">店铺：</Text>
        <Select
          mode="multiple"
          style={{ minWidth: 280 }}
          value={shopIds}
          onChange={setShopIds}
          options={shopOptions}
          placeholder="至少选 1 个店铺"
          maxTagCount="responsive"
          allowClear={false}
        />
        <Text type="secondary">数据源：</Text>
        <Select
          mode="multiple"
          style={{ minWidth: 260 }}
          value={sources}
          onChange={setSources}
          options={SOURCE_OPTIONS}
          placeholder="全部（不过滤）"
          maxTagCount="responsive"
          allowClear
        />
      </Space>
      <br />
      <Space wrap style={{ marginBottom: 12 }}>
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
          {shopIds.length > 1 && (
            <Tag color="gold" style={{ marginRight: 8 }}>
              跨 {shopIds.length} 店铺合并
            </Tag>
          )}
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

      <Modal
        title={(
          <Space>
            <InfoCircleOutlined style={{ color: '#faad14' }} />
            <span>推荐理由 · 类目内真实搜中明细</span>
          </Space>
        )}
        open={evidenceModal.open}
        onCancel={() => setEvidenceModal({ open: false, loading: false, keyword: '', evidence: null, items: [], shopId: null })}
        footer={null}
        width={680}
      >
        {evidenceModal.evidence && (
          <>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message={(
                <Space size={6} wrap>
                  <Text>关键词</Text>
                  <Tag color="blue" style={{ margin: 0 }}>{evidenceModal.keyword}</Tag>
                  <Text>在类目</Text>
                  <Tag color="purple" style={{ margin: 0 }}>
                    {evidenceModal.evidence.cat_name_ru || evidenceModal.evidence.cat_name || `cat#${evidenceModal.evidence.cat_id}`}
                  </Tag>
                </Space>
              )}
              description={(
                <div style={{ marginTop: 4, fontSize: 12 }}>
                  <Text strong style={{ color: '#389e0d' }}>{evidenceModal.evidence.products_verified}</Text> 款真实搜中 ·
                  {' '}曝光 <Text strong>{(evidenceModal.evidence.total_impressions || 0).toLocaleString()}</Text> ·
                  {' '}加购 <Text strong>{evidenceModal.evidence.total_add_to_cart || 0}</Text> ·
                  {' '}订单 <Text strong style={{ color: (evidenceModal.evidence.total_orders || 0) > 0 ? '#cf1322' : undefined }}>{evidenceModal.evidence.total_orders || 0}</Text>
                  <div style={{ marginTop: 4, color: '#888' }}>
                    系统由此推断"同类目其他商品也适合加这词" → 把此词加进本商品标题可能抢到一份搜索流量
                  </div>
                </div>
              )}
            />
            <List
              loading={evidenceModal.loading}
              bordered
              size="small"
              dataSource={evidenceModal.items}
              locale={{ emptyText: '无数据' }}
              renderItem={(it, idx) => (
                <List.Item>
                  <Space align="start" style={{ width: '100%' }}>
                    <span style={{ fontSize: 14, color: '#999', width: 22, textAlign: 'center' }}>#{idx + 1}</span>
                    {it.image_url && (
                      <Image src={it.image_url} width={42} height={42}
                             style={{ borderRadius: 4, objectFit: 'cover' }} preview={false}
                             fallback="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='42' height='42'%3E%3Crect fill='%23eee' width='42' height='42'/%3E%3C/svg%3E"
                      />
                    )}
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 12, fontWeight: 500 }}>{it.title || '(无标题)'}</div>
                      <Text type="secondary" style={{ fontSize: 11 }}>SKU {it.platform_sku_id || it.product_id}</Text>
                    </div>
                    <Space size={12} style={{ fontSize: 12 }}>
                      <span>曝光 <Text strong>{(it.total_impressions || 0).toLocaleString()}</Text></span>
                      <span>加购 <Text strong>{it.total_add_to_cart || 0}</Text></span>
                      <span>订单 <Text strong style={{ color: (it.total_orders || 0) > 0 ? '#cf1322' : undefined }}>{it.total_orders || 0}</Text></span>
                    </Space>
                  </Space>
                </List.Item>
              )}
            />
          </>
        )}
      </Modal>
    </div>
  )
}

export default CandidatesRollupTable
