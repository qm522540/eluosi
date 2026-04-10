import { useState, useEffect, useCallback } from 'react'
import {
  Typography, Card, Table, Tag, Select, Row, Col, Empty, DatePicker,
} from 'antd'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import {
  getPlatformComparison, getCampaignRanking, getProductRoi,
} from '@/api/ads'
import { PLATFORMS } from '@/utils/constants'

const { Text } = Typography
const { RangePicker } = DatePicker

const AdsAnalysis = ({ shopId, platform, searched }) => {
  const [platformData, setPlatformData] = useState([])
  const [rankingData, setRankingData] = useState([])
  const [productRoiData, setProductRoiData] = useState([])
  const [analysisLoading, setAnalysisLoading] = useState(false)
  const [rankSort, setRankSort] = useState('spend')
  const [dateRange, setDateRange] = useState([dayjs().subtract(6, 'day'), dayjs()])

  const fetchAnalysis = useCallback(async () => {
    if (!dateRange || dateRange.length !== 2) return
    setAnalysisLoading(true)
    const params = {
      start_date: dateRange[0].format('YYYY-MM-DD'),
      end_date: dateRange[1].format('YYYY-MM-DD'),
    }
    if (shopId) params.shop_id = shopId
    try {
      const [pRes, rRes, prRes] = await Promise.all([
        getPlatformComparison(params),
        getCampaignRanking({ ...params, sort_by: rankSort, limit: 10, platform }),
        getProductRoi({ ...params, platform }),
      ])
      setPlatformData(pRes.data || [])
      setRankingData(rRes.data || [])
      setProductRoiData(prRes.data || [])
    } catch {
      // ignore
    } finally {
      setAnalysisLoading(false)
    }
  }, [dateRange, shopId, platform, rankSort])

  useEffect(() => {
    if (searched) fetchAnalysis()
  }, [searched, shopId, platform, dateRange, rankSort])

  const getPlatformChartOption = () => {
    const labels = { wb: 'Wildberries', ozon: 'Ozon', yandex: 'Yandex' }
    const platforms = platformData.map(p => labels[p.platform] || p.platform)
    return {
      tooltip: { trigger: 'axis' },
      legend: { data: ['花费', '收入', 'ROAS'] },
      grid: { left: 60, right: 60, top: 40, bottom: 30 },
      xAxis: { type: 'category', data: platforms },
      yAxis: [
        { type: 'value', name: '金额 (₽)' },
        { type: 'value', name: 'ROAS', position: 'right' },
      ],
      series: [
        { name: '花费', type: 'bar', data: platformData.map(p => p.spend), itemStyle: { color: '#ff7875' }, barMaxWidth: 40 },
        { name: '收入', type: 'bar', data: platformData.map(p => p.revenue), itemStyle: { color: '#95de64' }, barMaxWidth: 40 },
        { name: 'ROAS', type: 'line', yAxisIndex: 1, data: platformData.map(p => p.roas), itemStyle: { color: '#faad14' } },
      ],
    }
  }

  if (!searched) {
    return <Card><Empty description="请选择平台和店铺后点击确定" /></Card>
  }

  return (
    <>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={24}>
          <RangePicker value={dateRange} onChange={setDateRange} allowClear={false}
            presets={[
              { label: '近7天', value: [dayjs().subtract(6, 'day'), dayjs()] },
              { label: '近30天', value: [dayjs().subtract(29, 'day'), dayjs()] },
              { label: '近90天', value: [dayjs().subtract(89, 'day'), dayjs()] },
            ]}
          />
        </Col>
      </Row>

      {/* 平台对比 */}
      <Card title="平台对比分析" size="small" style={{ marginBottom: 24 }} loading={analysisLoading}>
        {platformData.length > 0 ? (
          <>
            <ReactECharts option={getPlatformChartOption()} style={{ height: 280 }} />
            <Table size="small" dataSource={platformData} rowKey="platform" pagination={false} style={{ marginTop: 16 }}
              columns={[
                { title: '平台', dataIndex: 'platform', render: p => <Tag color={PLATFORMS[p]?.color}>{PLATFORMS[p]?.label || p}</Tag> },
                { title: '展示', dataIndex: 'impressions', render: v => v.toLocaleString() },
                { title: '点击', dataIndex: 'clicks', render: v => v.toLocaleString() },
                { title: 'CTR%', dataIndex: 'ctr', render: v => `${v}%` },
                { title: '花费', dataIndex: 'spend', render: v => `₽${v.toLocaleString()}` },
                { title: '收入', dataIndex: 'revenue', render: v => `₽${v.toLocaleString()}` },
                { title: 'ROAS', dataIndex: 'roas', render: v => <Text style={{ color: v >= 1 ? '#52c41a' : '#ff4d4f' }}>{v}x</Text> },
                { title: '转化率', dataIndex: 'conversion_rate', render: v => `${v}%` },
              ]}
            />
          </>
        ) : <Empty description="暂无多平台数据" />}
      </Card>

      {/* 活动排名 */}
      <Card title="活动TOP排名" size="small" style={{ marginBottom: 24 }}
        extra={
          <Select value={rankSort} onChange={setRankSort} size="small" style={{ width: 120 }}
            options={[
              { value: 'spend', label: '按花费排序' },
              { value: 'revenue', label: '按收入排序' },
              { value: 'clicks', label: '按点击排序' },
              { value: 'orders', label: '按订单排序' },
            ]}
          />
        }
      >
        <Table size="small" dataSource={rankingData} rowKey="campaign_id" pagination={false} loading={analysisLoading}
          columns={[
            { title: '排名', key: 'rank', width: 60, render: (_, __, i) => <Text strong>{i + 1}</Text> },
            { title: '活动名称', dataIndex: 'name', ellipsis: true },
            { title: '平台', dataIndex: 'platform', width: 110, render: p => <Tag color={PLATFORMS[p]?.color}>{PLATFORMS[p]?.label}</Tag> },
            { title: '花费', dataIndex: 'spend', width: 100, render: v => `₽${v.toLocaleString()}` },
            { title: '收入', dataIndex: 'revenue', width: 100, render: v => `₽${v.toLocaleString()}` },
            { title: '点击', dataIndex: 'clicks', width: 80 },
            { title: '订单', dataIndex: 'orders', width: 70 },
            { title: 'ROAS', dataIndex: 'roas', width: 80, render: v => <Text style={{ color: v >= 1 ? '#52c41a' : '#ff4d4f' }}>{v}x</Text> },
            { title: 'ACOS%', dataIndex: 'acos', width: 80, render: v => `${v}%` },
          ]}
        />
      </Card>

      {/* 商品ROI */}
      <Card title="商品级ROI分析" size="small">
        <Table size="small" dataSource={productRoiData} rowKey={(r) => `${r.listing_id || ''}_${r.group_name || ''}`} loading={analysisLoading}
          pagination={{ pageSize: 10, size: 'small' }}
          columns={[
            { title: '商品/广告组', dataIndex: 'group_name', ellipsis: true },
            { title: '商品ID', dataIndex: 'listing_id', width: 100, render: v => v || '-' },
            { title: '平台', dataIndex: 'platform', width: 100, render: p => <Tag color={PLATFORMS[p]?.color}>{PLATFORMS[p]?.label}</Tag> },
            { title: '花费', dataIndex: 'spend', width: 100, render: v => `₽${v}` },
            { title: '收入', dataIndex: 'revenue', width: 100, render: v => `₽${v}` },
            { title: 'ROAS', dataIndex: 'roas', width: 80, render: v => <Text style={{ color: v >= 1 ? '#52c41a' : '#ff4d4f' }}>{v}x</Text> },
            { title: 'CPA', dataIndex: 'cpa', width: 80, render: v => v ? `₽${v}` : '-' },
            { title: '订单', dataIndex: 'orders', width: 70 },
          ]}
        />
      </Card>
    </>
  )
}

export default AdsAnalysis
