import { useState, useEffect, useCallback, useMemo } from 'react'
import { Typography, Card, Space, Alert, message, Modal, Button } from 'antd'
import { ExclamationCircleOutlined } from '@ant-design/icons'
import { getShops } from '@/api/shops'
import {
  getSeoCandidates, refreshSeo, adoptSeoCandidate, batchIgnoreCandidates,
} from '@/api/seo'
import SeoFilterBar from './components/SeoFilterBar'
import SeoStatsCards from './components/SeoStatsCards'
import SeoCandidatesTable from './components/SeoCandidatesTable'

const { Title, Text } = Typography

const Optimize = () => {
  const [shops, setShops] = useState([])
  const [shopId, setShopId] = useState(null)
  const [days, setDays] = useState(30)
  const [roasThreshold, setRoasThreshold] = useState(2.0)
  const [source, setSource] = useState('all')
  const [status, setStatus] = useState('pending')
  const [keyword, setKeyword] = useState('')

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  const [page, setPage] = useState(1)
  const [size, setSize] = useState(20)

  const [selectedKeys, setSelectedKeys] = useState([])

  useEffect(() => {
    getShops({ page: 1, page_size: 100 })
      .then(r => {
        const items = (r.data?.items || []).filter(s => ['wb', 'ozon'].includes(s.platform))
        setShops(items)
        if (items.length && !shopId) setShopId(items[0].id)
      })
      .catch(() => setShops([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fetchCandidates = useCallback(async () => {
    if (!shopId) return
    setLoading(true)
    try {
      const res = await getSeoCandidates(shopId, {
        source, status, keyword: keyword.trim(), page, size,
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
  }, [shopId, source, status, keyword, page, size])

  useEffect(() => { fetchCandidates() }, [fetchCandidates])

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

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Title level={4} style={{ marginBottom: 4 }}>SEO 优化建议 · 付费词反哺自然词</Title>
        <Text type="secondary">
          扫描高 ROAS 付费词 + 同类目共性词 → 找出当前商品标题/属性未覆盖的反哺候选。一期仅基于付费数据（源 A）。
        </Text>
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="当前 SEO 分析基于付费广告数据 + 本店同类目聚合。"
        description={(
          <span>
            开通 <strong>WB Jam / Ozon Premium</strong> 后，会自动接入自然搜索词（源 B），分析精度约 3 倍提升。
            更多详情见「搜索词洞察」菜单。
          </span>
        )}
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
        />

        <SeoStatsCards totals={data?.totals} />

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
        />
      </Card>
    </div>
  )
}

export default Optimize
