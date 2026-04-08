import { useState, useEffect, useCallback } from 'react'
import {
  Typography, Card, Table, Button, Tag, Space, Select, Row, Col,
  Statistic, Modal, Form, InputNumber, message, DatePicker, Tooltip, Badge,
} from 'antd'
import {
  ReloadOutlined, EditOutlined, EyeOutlined,
  FundOutlined, DollarOutlined, AimOutlined, RiseOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import { getCampaigns, getCampaign, updateCampaign, getAdStats, getAdSummary } from '@/api/ads'
import { getShops } from '@/api/shops'
import { PLATFORMS, AD_STATUS, AD_TYPES } from '@/utils/constants'

const { Title } = Typography
const { RangePicker } = DatePicker

const Ads = () => {
  // 汇总数据
  const [summary, setSummary] = useState(null)
  const [summaryLoading, setSummaryLoading] = useState(false)

  // 活动列表
  const [campaigns, setCampaigns] = useState([])
  const [listLoading, setListLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [filterPlatform, setFilterPlatform] = useState(null)
  const [filterStatus, setFilterStatus] = useState(null)
  const [filterShopId, setFilterShopId] = useState(null)

  // 店铺列表（用于筛选）
  const [shops, setShops] = useState([])

  // 编辑弹窗
  const [editVisible, setEditVisible] = useState(false)
  const [editingCampaign, setEditingCampaign] = useState(null)
  const [editSubmitting, setEditSubmitting] = useState(false)
  const [editForm] = Form.useForm()

  // 详情弹窗
  const [detailVisible, setDetailVisible] = useState(false)
  const [detailData, setDetailData] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)

  // 统计图表
  const [statsData, setStatsData] = useState([])
  const [statsLoading, setStatsLoading] = useState(false)
  const [dateRange, setDateRange] = useState([dayjs().subtract(6, 'day'), dayjs()])

  // 加载店铺列表
  useEffect(() => {
    getShops({ page: 1, page_size: 100 }).then(res => {
      setShops(res.data.items || [])
    }).catch(() => {})
  }, [])

  // 加载汇总
  const fetchSummary = useCallback(async () => {
    setSummaryLoading(true)
    try {
      const params = {}
      if (filterShopId) params.shop_id = filterShopId
      if (filterPlatform) params.platform = filterPlatform
      const res = await getAdSummary(params)
      setSummary(res.data)
    } catch {
      setSummary(null)
    } finally {
      setSummaryLoading(false)
    }
  }, [filterShopId, filterPlatform])

  // 加载活动列表
  const fetchCampaigns = useCallback(async (p = page) => {
    setListLoading(true)
    try {
      const params = { page: p, page_size: 20 }
      if (filterPlatform) params.platform = filterPlatform
      if (filterStatus) params.status = filterStatus
      if (filterShopId) params.shop_id = filterShopId
      const res = await getCampaigns(params)
      setCampaigns(res.data.items)
      setTotal(res.data.total)
    } catch {
      message.error('获取广告活动列表失败')
    } finally {
      setListLoading(false)
    }
  }, [page, filterPlatform, filterStatus, filterShopId])

  // 加载统计趋势
  const fetchStats = useCallback(async () => {
    if (!dateRange || dateRange.length !== 2) return
    setStatsLoading(true)
    try {
      const params = {
        start_date: dateRange[0].format('YYYY-MM-DD'),
        end_date: dateRange[1].format('YYYY-MM-DD'),
      }
      if (filterShopId) params.shop_id = filterShopId
      if (filterPlatform) params.platform = filterPlatform
      const res = await getAdStats(params)
      setStatsData(res.data || [])
    } catch {
      setStatsData([])
    } finally {
      setStatsLoading(false)
    }
  }, [dateRange, filterShopId, filterPlatform])

  useEffect(() => {
    fetchSummary()
    fetchCampaigns(1)
    setPage(1)
  }, [filterPlatform, filterStatus, filterShopId])

  useEffect(() => {
    fetchStats()
  }, [fetchStats])

  // 查看详情
  const handleDetail = async (id) => {
    setDetailLoading(true)
    setDetailVisible(true)
    try {
      const res = await getCampaign(id)
      setDetailData(res.data)
    } catch {
      message.error('获取广告详情失败')
    } finally {
      setDetailLoading(false)
    }
  }

  // 编辑
  const handleEdit = (record) => {
    setEditingCampaign(record)
    editForm.setFieldsValue({
      daily_budget: record.daily_budget,
      total_budget: record.total_budget,
      status: record.status,
    })
    setEditVisible(true)
  }

  const handleEditSubmit = async () => {
    try {
      const values = await editForm.validateFields()
      setEditSubmitting(true)
      await updateCampaign(editingCampaign.id, values)
      message.success('广告活动更新成功')
      setEditVisible(false)
      fetchCampaigns()
      fetchSummary()
    } catch (err) {
      if (err.errorFields) return
      message.error(err.message || '更新失败')
    } finally {
      setEditSubmitting(false)
    }
  }

  // 表格列
  const columns = [
    {
      title: '活动名称',
      dataIndex: 'name',
      key: 'name',
      ellipsis: true,
      render: (text, record) => (
        <a onClick={() => handleDetail(record.id)}>{text || `Campaign #${record.id}`}</a>
      ),
    },
    {
      title: '平台',
      dataIndex: 'platform',
      key: 'platform',
      width: 130,
      render: (p) => {
        const info = PLATFORMS[p]
        return info ? <Tag color={info.color}>{info.label}</Tag> : p
      },
    },
    {
      title: '广告类型',
      dataIndex: 'ad_type',
      key: 'ad_type',
      width: 110,
      render: (t) => AD_TYPES[t]?.label || t,
    },
    {
      title: '日预算',
      dataIndex: 'daily_budget',
      key: 'daily_budget',
      width: 110,
      align: 'right',
      render: (v) => v != null ? `₽${v.toLocaleString()}` : '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (s) => {
        const info = AD_STATUS[s]
        return info ? <Badge color={info.color} text={info.label} /> : s
      },
    },
    {
      title: '开始日期',
      dataIndex: 'start_date',
      key: 'start_date',
      width: 110,
      render: (v) => v || '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 140,
      render: (_, record) => (
        <Space size="small">
          <Tooltip title="查看详情">
            <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => handleDetail(record.id)}>
              详情
            </Button>
          </Tooltip>
          <Tooltip title="调整预算/状态">
            <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>
              编辑
            </Button>
          </Tooltip>
        </Space>
      ),
    },
  ]

  // ECharts 配置：花费与点击趋势
  const getChartOption = () => {
    // 按日期聚合（多平台合并同一天）
    const dateMap = {}
    statsData.forEach(item => {
      if (!dateMap[item.stat_date]) {
        dateMap[item.stat_date] = { spend: 0, clicks: 0, impressions: 0, revenue: 0 }
      }
      dateMap[item.stat_date].spend += item.spend
      dateMap[item.stat_date].clicks += item.clicks
      dateMap[item.stat_date].impressions += item.impressions
      dateMap[item.stat_date].revenue += item.revenue
    })
    const dates = Object.keys(dateMap).sort()
    const spendArr = dates.map(d => dateMap[d].spend)
    const clicksArr = dates.map(d => dateMap[d].clicks)
    const revenueArr = dates.map(d => dateMap[d].revenue)

    return {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
      },
      legend: { data: ['花费 (₽)', '收入 (₽)', '点击'] },
      grid: { left: 60, right: 60, top: 40, bottom: 30 },
      xAxis: { type: 'category', data: dates },
      yAxis: [
        { type: 'value', name: '金额 (₽)', position: 'left' },
        { type: 'value', name: '点击', position: 'right' },
      ],
      series: [
        {
          name: '花费 (₽)',
          type: 'bar',
          data: spendArr,
          itemStyle: { color: '#ff7875' },
          barMaxWidth: 30,
        },
        {
          name: '收入 (₽)',
          type: 'bar',
          data: revenueArr,
          itemStyle: { color: '#95de64' },
          barMaxWidth: 30,
        },
        {
          name: '点击',
          type: 'line',
          yAxisIndex: 1,
          data: clicksArr,
          smooth: true,
          itemStyle: { color: '#597ef7' },
        },
      ],
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0 }}>广告管理</Title>
        <Space>
          <Select
            placeholder="全部店铺"
            allowClear
            style={{ width: 160 }}
            value={filterShopId}
            onChange={setFilterShopId}
            options={shops.map(s => ({ value: s.id, label: s.name }))}
          />
          <Select
            placeholder="全部平台"
            allowClear
            style={{ width: 140 }}
            value={filterPlatform}
            onChange={setFilterPlatform}
            options={[
              { value: 'wb', label: 'Wildberries' },
              { value: 'ozon', label: 'Ozon' },
              { value: 'yandex', label: 'Yandex Market' },
            ]}
          />
          <Select
            placeholder="全部状态"
            allowClear
            style={{ width: 120 }}
            value={filterStatus}
            onChange={setFilterStatus}
            options={Object.entries(AD_STATUS).map(([k, v]) => ({ value: k, label: v.label }))}
          />
          <Button icon={<ReloadOutlined />} onClick={() => { fetchCampaigns(); fetchSummary(); fetchStats() }}>
            刷新
          </Button>
        </Space>
      </div>

      {/* 汇总卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card size="small" loading={summaryLoading}>
            <Statistic
              title="总展示"
              value={summary?.total_impressions || 0}
              prefix={<FundOutlined />}
              valueStyle={{ color: '#597ef7' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" loading={summaryLoading}>
            <Statistic
              title="总点击"
              value={summary?.total_clicks || 0}
              prefix={<AimOutlined />}
              suffix={summary?.avg_ctr != null ? <span style={{ fontSize: 14, color: '#999' }}>CTR {summary.avg_ctr}%</span> : null}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" loading={summaryLoading}>
            <Statistic
              title="总花费"
              value={summary?.total_spend || 0}
              prefix={<DollarOutlined />}
              precision={2}
              suffix="₽"
              valueStyle={{ color: '#ff7875' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" loading={summaryLoading}>
            <Statistic
              title="ROAS"
              value={summary?.overall_roas || 0}
              prefix={<RiseOutlined />}
              precision={2}
              suffix="x"
              valueStyle={{ color: summary?.overall_roas >= 1 ? '#52c41a' : '#ff4d4f' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 趋势图表 */}
      <Card
        title="广告趋势"
        size="small"
        style={{ marginBottom: 24 }}
        extra={
          <RangePicker
            value={dateRange}
            onChange={setDateRange}
            allowClear={false}
            presets={[
              { label: '近7天', value: [dayjs().subtract(6, 'day'), dayjs()] },
              { label: '近30天', value: [dayjs().subtract(29, 'day'), dayjs()] },
            ]}
          />
        }
      >
        <ReactECharts
          option={getChartOption()}
          style={{ height: 300 }}
          showLoading={statsLoading}
        />
      </Card>

      {/* 活动列表 */}
      <Card title="广告活动" size="small">
        <Table
          columns={columns}
          dataSource={campaigns}
          rowKey="id"
          loading={listLoading}
          pagination={{
            current: page,
            total,
            pageSize: 20,
            showTotal: (t) => `共 ${t} 个活动`,
            onChange: (p) => { setPage(p); fetchCampaigns(p) },
          }}
        />
      </Card>

      {/* 编辑弹窗 */}
      <Modal
        title={`编辑广告活动 — ${editingCampaign?.name || ''}`}
        open={editVisible}
        onOk={handleEditSubmit}
        onCancel={() => setEditVisible(false)}
        confirmLoading={editSubmitting}
        destroyOnClose
      >
        <Form form={editForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="daily_budget" label="日预算 (₽)">
            <InputNumber min={0} step={100} style={{ width: '100%' }} placeholder="不限" />
          </Form.Item>
          <Form.Item name="total_budget" label="总预算 (₽)">
            <InputNumber min={0} step={100} style={{ width: '100%' }} placeholder="不限" />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select options={[
              { value: 'active', label: '投放中' },
              { value: 'paused', label: '暂停' },
            ]} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 详情弹窗 */}
      <Modal
        title="广告活动详情"
        open={detailVisible}
        onCancel={() => setDetailVisible(false)}
        footer={null}
        width={640}
        loading={detailLoading}
      >
        {detailData && (
          <div>
            <Row gutter={[16, 12]} style={{ marginBottom: 16 }}>
              <Col span={12}><strong>名称：</strong>{detailData.name || '-'}</Col>
              <Col span={12}>
                <strong>平台：</strong>
                <Tag color={PLATFORMS[detailData.platform]?.color}>{PLATFORMS[detailData.platform]?.label}</Tag>
              </Col>
              <Col span={12}><strong>类型：</strong>{AD_TYPES[detailData.ad_type]?.label || detailData.ad_type}</Col>
              <Col span={12}>
                <strong>状态：</strong>
                <Badge color={AD_STATUS[detailData.status]?.color} text={AD_STATUS[detailData.status]?.label || detailData.status} />
              </Col>
              <Col span={12}><strong>日预算：</strong>{detailData.daily_budget != null ? `₽${detailData.daily_budget}` : '不限'}</Col>
              <Col span={12}><strong>总预算：</strong>{detailData.total_budget != null ? `₽${detailData.total_budget}` : '不限'}</Col>
              <Col span={12}><strong>开始日期：</strong>{detailData.start_date || '-'}</Col>
              <Col span={12}><strong>结束日期：</strong>{detailData.end_date || '-'}</Col>
              <Col span={24}><strong>平台活动ID：</strong>{detailData.platform_campaign_id || '-'}</Col>
            </Row>

            {detailData.ad_groups?.length > 0 && (
              <>
                <Title level={5} style={{ marginTop: 16 }}>广告组</Title>
                <Table
                  size="small"
                  dataSource={detailData.ad_groups}
                  rowKey="id"
                  pagination={false}
                  columns={[
                    { title: '名称', dataIndex: 'name', key: 'name' },
                    { title: '出价', dataIndex: 'bid', key: 'bid', width: 100, render: v => v != null ? `₽${v}` : '-' },
                    {
                      title: '状态', dataIndex: 'status', key: 'status', width: 80,
                      render: s => <Badge color={AD_STATUS[s]?.color || 'default'} text={AD_STATUS[s]?.label || s} />,
                    },
                  ]}
                />
              </>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}

export default Ads
