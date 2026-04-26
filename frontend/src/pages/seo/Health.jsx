import { useState, useEffect, useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Typography, Card, Alert, message } from 'antd'
import { getShops } from '@/api/shops'
import { getSeoHealth } from '@/api/seo'
import HealthFilterBar from './components/HealthFilterBar'
import HealthStatsCards from './components/HealthStatsCards'
import HealthProductsTable from './components/HealthProductsTable'

const { Title, Text } = Typography

const Health = () => {
  const [searchParams] = useSearchParams()
  const [shops, setShops] = useState([])
  const [shopId, setShopId] = useState(null)
  const [scoreRange, setScoreRange] = useState('all')
  const [sort, setSort] = useState('score_asc')
  const [keyword, setKeyword] = useState('')

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)

  const [page, setPage] = useState(1)
  const [size, setSize] = useState(20)

  useEffect(() => {
    getShops({ page: 1, page_size: 100 })
      .then(r => {
        const items = (r.data?.items || []).filter(s => ['wb', 'ozon'].includes(s.platform))
        setShops(items)
        const urlShopId = Number(searchParams.get('shopId'))
        const preferId = urlShopId && items.find(s => s.id === urlShopId) ? urlShopId : (items[0]?.id || null)
        if (preferId && !shopId) setShopId(preferId)
      })
      .catch(() => setShops([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fetchData = useCallback(async () => {
    if (!shopId) return
    setLoading(true)
    try {
      const res = await getSeoHealth(shopId, {
        score_range: scoreRange, sort, keyword: keyword.trim(), page, size,
      })
      if (res.code === 0) {
        setData(res.data)
      } else {
        message.error(res.msg || '拉取失败')
      }
    } catch (e) {
      message.error(e?.response?.data?.msg || '网络错误')
    } finally {
      setLoading(false)
    }
  }, [shopId, scoreRange, sort, keyword, page, size])

  useEffect(() => { fetchData() }, [fetchData])

  const pagination = useMemo(() => ({
    current: page,
    pageSize: size,
    total: data?.totals?.total || 0,
    showSizeChanger: true,
    pageSizeOptions: [10, 20, 50, 100],
    showTotal: (t) => `共 ${t} 条（全店 ${data?.totals?.all || 0}）`,
  }), [page, size, data])

  const onPaginationChange = (p) => {
    if (p.current && p.current !== page) setPage(p.current)
    if (p.pageSize && p.pageSize !== size) {
      setSize(p.pageSize)
      setPage(1)
    }
  }

  const emptyAll = data?.totals?.all === 0

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Title level={4} style={{ marginBottom: 4 }}>SEO 健康诊断 · 商品级 0-100 分</Title>
        <Text type="secondary">
          评分维度：关键词覆盖率 60% + 标题长度 20% + 描述长度 20%。
          默认按分数升序 —— 最差的排在最前，点「AI 优化标题」当前页弹窗自动用 Top 3 候选词生成新标题（也可展开行精挑细选）。
        </Text>
      </div>

      {data?.organic_data_range && (
        <Alert
          type={data.organic_data_range.has_data ? 'info' : 'warning'}
          showIcon
          style={{ marginBottom: 12 }}
          message={
            data.organic_data_range.has_data ? (
              <span>
                📊 自然流量数据范围：
                <strong style={{ margin: '0 4px' }}>
                  {data.organic_data_range.earliest} ~ {data.organic_data_range.latest}
                </strong>
                （实际有 <strong>{data.organic_data_range.days_with_data}</strong> 天数据 / 最近 30 天窗口，
                共 {data.organic_data_range.total_rows.toLocaleString()} 条搜索词记录）
              </span>
            ) : (
              <span>
                ⚠️ 自然流量数据为空 —— 该店铺可能未开通订阅（WB Jam / Ozon Premium），
                或订阅刚开通数据还未同步。下方"自然流量"列将全部显示 —
              </span>
            )
          }
        />
      )}

      <Card>
        <HealthFilterBar
          shops={shops}
          shopId={shopId}
          onShopChange={(v) => { setShopId(v); setPage(1) }}
          scoreRange={scoreRange}
          onScoreRangeChange={(v) => { setScoreRange(v); setPage(1) }}
          sort={sort}
          onSortChange={(v) => { setSort(v); setPage(1) }}
          keyword={keyword}
          onKeywordChange={setKeyword}
          onReload={() => { setPage(1); fetchData() }}
        />

        <HealthStatsCards totals={data?.totals} />

        {emptyAll && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message="该店铺暂无商品"
            description="请先在「商品管理 → 商品列表」同步或新建商品"
          />
        )}

        <HealthProductsTable
          shopId={shopId}
          data={data?.items}
          loading={loading}
          pagination={pagination}
          onPaginationChange={onPaginationChange}
        />
      </Card>
    </div>
  )
}

export default Health
