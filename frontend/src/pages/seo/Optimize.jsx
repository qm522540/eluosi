import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Typography, Card, Space, Alert, message, Modal, Button, Tag, Tabs } from 'antd'
import { ExclamationCircleOutlined, RobotOutlined, CloseOutlined } from '@ant-design/icons'
import { getShops } from '@/api/shops'
import {
  getSeoCandidates, refreshSeo, adoptSeoCandidate, batchIgnoreCandidates,
} from '@/api/seo'
import SeoFilterBar from './components/SeoFilterBar'
import SeoStatsCards from './components/SeoStatsCards'
import SeoCandidatesTable from './components/SeoCandidatesTable'
import AiTitleModal from './components/AiTitleModal'
import ChampionKeywordsCard from './components/ChampionKeywordsCard'
import KeywordRollupTab from './components/KeywordRollupTab'

const { Title, Text } = Typography

const Optimize = () => {
  const [searchParams, setSearchParams] = useSearchParams()
  const autoAiConsumed = useRef(false)

  const [shops, setShops] = useState([])
  const [shopId, setShopId] = useState(null)
  const [days, setDays] = useState(30)
  const [roasThreshold, setRoasThreshold] = useState(2.0)
  const [source, setSource] = useState('all')
  const [status, setStatus] = useState('pending')
  const [keyword, setKeyword] = useState('')
  const [productFilter, setProductFilter] = useState(null)
  const [hideCovered, setHideCovered] = useState(true)

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  const [page, setPage] = useState(1)
  const [size, setSize] = useState(20)

  const [selectedKeys, setSelectedKeys] = useState([])
  const [aiModal, setAiModal] = useState({ open: false, product: null, candidates: [] })
  const [activeTab, setActiveTab] = useState('by-product')

  useEffect(() => {
    getShops({ page: 1, page_size: 100 })
      .then(r => {
        const items = (r.data?.items || []).filter(s => ['wb', 'ozon'].includes(s.platform))
        setShops(items)
        const urlShopId = Number(searchParams.get('shopId'))
        const urlProductId = Number(searchParams.get('productId'))
        const preferId = urlShopId && items.find(s => s.id === urlShopId) ? urlShopId : (items[0]?.id || null)
        if (preferId && !shopId) setShopId(preferId)
        if (urlProductId) setProductFilter(urlProductId)
      })
      .catch(() => setShops([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fetchCandidates = useCallback(async () => {
    if (!shopId) return
    setLoading(true)
    try {
      const res = await getSeoCandidates(shopId, {
        source, status, keyword: keyword.trim(),
        product_id: productFilter || undefined,
        hide_covered: hideCovered,
        page, size,
      })
      if (res.code === 0) {
        setData(res.data)
        setSelectedKeys([])
      } else {
        message.error(res.msg || '拉取失败')
      }
    } catch (e) {
      message.error(e?.response?.data?.msg || '网络错误')
    } finally {
      setLoading(false)
    }
  }, [shopId, source, status, keyword, productFilter, hideCovered, page, size])

  useEffect(() => { fetchCandidates() }, [fetchCandidates])

  // URL autoAi=1 → 首次拉到数据后自动选 Top 5 + 打开 AI Modal（Health 闭环）
  useEffect(() => {
    if (autoAiConsumed.current) return
    if (searchParams.get('autoAi') !== '1') return
    if (!data?.items?.length) return
    const topRows = data.items.slice(0, 5)
    if (!topRows.length) return
    const first = topRows[0]
    setSelectedKeys(topRows.map(r => r.id))
    setAiModal({
      open: true,
      product: {
        id: first.product_id,
        name: first.product_name,
        currentTitle: first.current_title,
      },
      candidates: topRows,
    })
    autoAiConsumed.current = true
    const next = new URLSearchParams(searchParams)
    next.delete('autoAi')
    setSearchParams(next, { replace: true })
  }, [data, searchParams, setSearchParams])

  const handleRefresh = async () => {
    if (!shopId) return
    setRefreshing(true)
    try {
      const res = await refreshSeo(shopId, {
        days, roas_threshold: roasThreshold, min_orders: 1,
      })
      if (res.code === 0) {
        const d = res.data || {}
        message.success(`引擎完成：扫描 ${d.analyzed_pairs} 对，候选 ${d.candidates}，写入 ${d.written}`)
        fetchCandidates()
      } else {
        message.error(res.msg || '引擎失败')
      }
    } catch (e) {
      message.error(e?.response?.data?.msg || '引擎调用失败')
    } finally {
      setRefreshing(false)
    }
  }

  const handleAdopt = async (row) => {
    if (!shopId) return
    try {
      const res = await adoptSeoCandidate(shopId, row.id)
      if (res.code === 0) {
        message.success(`已将「${row.keyword}」加入候选`)
        fetchCandidates()
      } else {
        message.error(res.msg || '操作失败')
      }
    } catch (e) {
      message.error(e?.response?.data?.msg || '网络错误')
    }
  }

  const handleOpenAiTitle = () => {
    if (!selectedKeys.length || !data?.items?.length) return
    const rows = data.items.filter(r => selectedKeys.includes(r.id))
    if (!rows.length) return
    const productIds = [...new Set(rows.map(r => r.product_id))]
    if (productIds.length > 1) {
      message.warning(`当前选中涉及 ${productIds.length} 个不同商品，AI 生成标题只能针对单个商品。请取消跨商品选择后再试。`)
      return
    }
    const first = rows[0]
    setAiModal({
      open: true,
      product: {
        id: first.product_id,
        name: first.product_name,
        currentTitle: first.current_title,
      },
      candidates: rows,
    })
  }

  const handleIgnore = (ids) => {
    const idsArr = Array.isArray(ids) ? ids : [ids]
    if (!idsArr.length || !shopId) return
    Modal.confirm({
      title: `忽略 ${idsArr.length} 个候选词？`,
      icon: <ExclamationCircleOutlined />,
      content: '忽略后将从待处理列表移除。后续再刷引擎也不会自动变回待处理（直到状态手动置回或重新 adopt）。',
      okText: '确认忽略',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const res = await batchIgnoreCandidates(shopId, idsArr)
          if (res.code === 0) {
            message.success(`已忽略 ${res.data?.updated || 0} 条`)
            setSelectedKeys([])
            fetchCandidates()
          } else {
            message.error(res.msg || '操作失败')
          }
        } catch (e) {
          message.error(e?.response?.data?.msg || '网络错误')
        }
      },
    })
  }

  const pagination = useMemo(() => ({
    current: page,
    pageSize: size,
    total: data?.totals?.total || 0,
    showSizeChanger: true,
    pageSizeOptions: [10, 20, 50, 100],
    showTotal: (t) => `共 ${t} 条`,
  }), [page, size, data])

  const onPaginationChange = (p) => {
    if (p.current && p.current !== page) setPage(p.current)
    if (p.pageSize && p.pageSize !== size) {
      setSize(p.pageSize)
      setPage(1)
    }
  }

  const noEmpty = data?.totals?.total === 0 && status === 'pending'

  const byProductTab = (
    <>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={(
          <span>
            <strong>每一行 = 一条反哺建议</strong>：系统发现「<Text code>商品 A</Text>」可以在俄语标题里加上「<Text code>关键词 X</Text>」，
            因为有买家这么搜过、但你当前标题/属性里没写这词 —— 加上就有机会吃到这些免费流量。
          </span>
        )}
        description={(
          <div style={{ marginTop: 6 }}>
            <div>
              <Text type="secondary">举例：</Text>
              <Text>商品「Серьги шары крупные」+ 关键词「серьги треугольные」（35 次月曝光、1 单）→ 改标题加上这个词，预计月增 40+ 曝光。</Text>
            </div>
            <div style={{ marginTop: 6 }}>
              <Text strong>怎么用（3 步闭环）：</Text>
              <Text> ① 勾同一商品的若干高分词（建议 3-8 个） ② 点顶部「AI 生成标题」 ③ 复制新俄语标题去商品列表粘贴保存。</Text>
            </div>
            <div style={{ marginTop: 6, color: '#999', fontSize: 12 }}>
              推荐从「SEO 健康诊断」页选差商品 → 点「AI 优化标题」跳进来，系统自动按商品筛 + 选 Top 5，闭环更顺。
            </div>
          </div>
        )}
      />

      {productFilter && (
        <Alert
          type="warning"
          showIcon={false}
          style={{ marginBottom: 16 }}
          message={(
            <Space>
              <Text>当前过滤商品 ID：</Text>
              <Tag color="purple">{productFilter}</Tag>
              <Text type="secondary">（来自 SEO 健康诊断跳转）</Text>
              <Button
                size="small"
                type="link"
                icon={<CloseOutlined />}
                onClick={() => { setProductFilter(null); setPage(1) }}
              >
                清除过滤
              </Button>
            </Space>
          )}
        />
      )}

      <ChampionKeywordsCard
        shopId={shopId}
        onPickKeyword={(kw) => {
          setKeyword(kw)
          setStatus('pending')
          setSource('all')
          setPage(1)
          setSelectedKeys([])
        }}
      />

      <Card>
        <SeoFilterBar
          shops={shops}
          shopId={shopId}
          onShopChange={(v) => { setShopId(v); setPage(1); setSelectedKeys([]) }}
          days={days}
          onDaysChange={setDays}
          roasThreshold={roasThreshold}
          onRoasChange={(v) => setRoasThreshold(v || 2.0)}
          source={source}
          onSourceChange={(v) => { setSource(v); setPage(1) }}
          status={status}
          onStatusChange={(v) => { setStatus(v); setPage(1) }}
          keyword={keyword}
          onKeywordChange={setKeyword}
          onRefresh={handleRefresh}
          refreshing={refreshing}
          onReload={() => { setPage(1); fetchCandidates() }}
          hideCovered={hideCovered}
          onHideCoveredChange={(v) => { setHideCovered(v); setPage(1) }}
        />

        <SeoStatsCards
          totals={data?.totals}
          currentSource={source}
          onSelectWithOrders={(v) => { setSource(v); setPage(1); setSelectedKeys([]) }}
        />

        {selectedKeys.length > 0 && (
          <div style={{
            padding: '8px 12px',
            marginBottom: 12,
            background: '#fffbe6',
            border: '1px solid #ffe58f',
            borderRadius: 4,
          }}>
            <Space>
              <Text>已选 <strong>{selectedKeys.length}</strong> 个候选词</Text>
              <Button
                size="small"
                type="primary"
                icon={<RobotOutlined />}
                onClick={handleOpenAiTitle}
              >
                AI 生成标题
              </Button>
              <Button size="small" danger onClick={() => handleIgnore(selectedKeys)}>批量忽略</Button>
              <Button size="small" onClick={() => setSelectedKeys([])}>清空</Button>
            </Space>
          </div>
        )}

        {noEmpty && !loading && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            message="当前店铺暂无候选词。可能原因："
            description={(
              <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
                <li>引擎还未跑过 —— 点右上「刷新引擎」扫描近 {days} 天付费数据</li>
                <li>没有达到 ROAS ≥ {roasThreshold} 且订单 ≥ 1 的付费词 —— 可调低 ROAS 阈值</li>
                <li>所有高 ROAS 词标题/属性均已覆盖 —— 这也是好事</li>
              </ul>
            )}
          />
        )}

        <SeoCandidatesTable
          data={data?.items}
          loading={loading}
          selectedKeys={selectedKeys}
          onSelectChange={setSelectedKeys}
          onAdopt={handleAdopt}
          onIgnore={handleIgnore}
          pagination={pagination}
          onPaginationChange={onPaginationChange}
          platform={shops.find(s => s.id === shopId)?.platform}
        />
      </Card>

      <AiTitleModal
        open={aiModal.open}
        onClose={() => setAiModal({ open: false, product: null, candidates: [] })}
        shopId={shopId}
        productId={aiModal.product?.id}
        productName={aiModal.product?.name}
        currentTitle={aiModal.product?.currentTitle}
        selectedCandidates={aiModal.candidates}
      />
    </>
  )

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Title level={4} style={{ marginBottom: 4 }}>SEO 优化建议 · 反哺候选词库</Title>
        <Text type="secondary">
          基于买家真实搜索数据，告诉你「哪个商品的俄语标题里应该加哪些关键词」才能多吃免费曝光。
        </Text>
      </div>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'by-product',
            label: '按商品看（反哺候选）',
            children: byProductTab,
          },
          {
            key: 'by-keyword',
            label: '店级关键词 TOP',
            children: (
              <KeywordRollupTab
                shops={shops}
                shopId={shopId}
                onShopChange={(v) => { setShopId(v); setPage(1); setSelectedKeys([]) }}
                onJumpToProduct={({ productId, keyword: kw }) => {
                  setProductFilter(productId)
                  setKeyword(kw)
                  setSource('all')
                  setStatus('pending')
                  setPage(1)
                  setSelectedKeys([])
                  setActiveTab('by-product')
                  message.info('已跳到「按商品看」Tab，已按该商品 + 关键词筛选')
                }}
              />
            ),
          },
        ]}
      />
    </div>
  )
}

export default Optimize
