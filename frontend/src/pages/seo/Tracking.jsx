import { useState, useEffect, useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Typography, Card, Alert, message, Space } from 'antd'
import { getShops } from '@/api/shops'
import { getKeywordTracking } from '@/api/seo'
import TrackingFilterBar from './components/TrackingFilterBar'
import TrackingStatsCards from './components/TrackingStatsCards'
import TrackingTable from './components/TrackingTable'
import TrackingInsightCard from './components/TrackingInsightCard'

const { Title, Text, Paragraph } = Typography

const Tracking = () => {
  const [searchParams] = useSearchParams()
  const [shops, setShops] = useState([])
  const [shopId, setShopId] = useState(null)
  const [dateRange, setDateRange] = useState(7)
  const [sort, setSort] = useState('impressions_desc')
  const [keyword, setKeyword] = useState('')
  const [minImpressions, setMinImpressions] = useState(0)
  const [alertOnly, setAlertOnly] = useState(false)

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
      const res = await getKeywordTracking(shopId, {
        date_range: dateRange, sort,
        keyword: keyword.trim(),
        min_impressions: minImpressions || 0,
        alert_only: alertOnly,
        page, size,
      })
      if (res.code === 0) setData(res.data)
      else message.error(res.msg || '拉取失败')
    } catch (e) {
      message.error(e?.response?.data?.msg || '网络错误')
    } finally {
      setLoading(false)
    }
  }, [shopId, dateRange, sort, keyword, minImpressions, alertOnly, page, size])

  useEffect(() => { fetchData() }, [fetchData])

  const pagination = useMemo(() => ({
    current: page,
    pageSize: size,
    total: data?.total || 0,
    showSizeChanger: true,
    pageSizeOptions: [10, 20, 50, 100],
    showTotal: (t) => `共 ${t} 个核心词`,
  }), [page, size, data])

  const onPaginationChange = (p) => {
    if (p.current && p.current !== page) setPage(p.current)
    if (p.pageSize && p.pageSize !== size) {
      setSize(p.pageSize)
      setPage(1)
    }
  }

  const notReady = data?.data_status === 'not_ready'
  const currentShop = shops.find(s => s.id === shopId)

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Title level={4} style={{ marginBottom: 4 }}>关键词表现追踪 · 环比趋势 + 下滑预警</Title>
        <Text type="secondary">
          看本期（近 N 天）vs 上期的曝光 / 订单 / 营收变化，发现下滑词和新增词。
          点「下钻」查看哪些商品靠这个词带流量，一键跳 AI 优化标题。
        </Text>
      </div>

      <Card>
        <TrackingFilterBar
          shops={shops}
          shopId={shopId}
          onShopChange={(v) => { setShopId(v); setPage(1) }}
          dateRange={dateRange}
          onDateRangeChange={(v) => { setDateRange(v); setPage(1) }}
          sort={sort}
          onSortChange={(v) => { setSort(v); setPage(1) }}
          keyword={keyword}
          onKeywordChange={setKeyword}
          minImpressions={minImpressions}
          onMinImpressionsChange={(v) => { setMinImpressions(v); setPage(1) }}
          alertOnly={alertOnly}
          onAlertOnlyChange={(v) => { setAlertOnly(v); setPage(1) }}
          onReload={() => { setPage(1); fetchData() }}
        />

        {notReady ? (
          <Alert
            type="warning"
            showIcon
            style={{ marginTop: 8 }}
            message={`${currentShop?.name || '该店铺'} 暂无搜索词数据`}
            description={
              <Space direction="vertical" size={4}>
                <Text>{data?.hint || '等平台订阅开通后，每日凌晨自动拉取'}</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  开通订阅后，可在 SEO 管理 → 自然搜索词 页面点「刷新候选池」手动触发一次同步。
                </Text>
              </Space>
            }
          />
        ) : (
          <>
            <TrackingInsightCard
              highlights={data?.highlights}
              onFilterByKeyword={(kw) => { setKeyword(kw); setAlertOnly(false); setPage(1) }}
              onSwitchAlertOnly={() => { setAlertOnly(true); setSort('drop_desc'); setKeyword(''); setPage(1) }}
              onSwitchNewOnly={() => { setSort('new_desc'); setAlertOnly(false); setKeyword(''); setPage(1) }}
            />

            <TrackingStatsCards totals={data?.totals} period={data?.period} />

            {data?.period && (
              <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>
                对比区间：本期 {data.period.cur_start} ~ {data.period.cur_end} · 上期 {data.period.prev_start} ~ {data.period.prev_end}
                {data.position_hint && (
                  <> &nbsp;·&nbsp; <Text type="warning" style={{ fontSize: 12 }}>{data.position_hint}</Text></>
                )}
              </Paragraph>
            )}

            <TrackingTable
              shopId={shopId}
              data={data?.items}
              loading={loading}
              pagination={pagination}
              onPaginationChange={onPaginationChange}
              positionHint={data?.position_hint}
            />
          </>
        )}
      </Card>
    </div>
  )
}

export default Tracking
