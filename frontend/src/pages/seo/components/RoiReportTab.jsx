import { useState, useEffect, useCallback } from 'react'
import {
  Typography, Card, Alert, Segmented, Button, Table, Tag, Space, Row, Col,
  Statistic, Progress, message, Tooltip,
} from 'antd'
import {
  EyeOutlined, ShoppingCartOutlined, DollarOutlined, SyncOutlined,
  ArrowUpOutlined, ArrowDownOutlined, ClockCircleOutlined,
} from '@ant-design/icons'
import { getRoiReport } from '@/api/seo'

const { Text, Paragraph } = Typography

const statCardStyle = { background: '#fafbff', borderColor: '#e6edff' }

const STATUS_META = {
  completed: { color: 'success', label: '观察完成' },
  observing: { color: 'processing', label: '观察中' },
}

const DeltaPct = ({ pct, positive_good = true }) => {
  if (pct === null || pct === undefined) return <Text type="secondary">新基线</Text>
  const color = (pct > 0) === positive_good
    ? (Math.abs(pct) >= 10 ? '#3f8600' : '#666')
    : (Math.abs(pct) >= 10 ? '#cf1322' : '#666')
  const sign = pct > 0 ? '+' : ''
  const Icon = pct > 0 ? ArrowUpOutlined : (pct < 0 ? ArrowDownOutlined : null)
  return (
    <span style={{ color, fontWeight: Math.abs(pct) >= 10 ? 600 : 400 }}>
      {Icon && <Icon />} {sign}{pct}%
    </span>
  )
}

const RoiReportTab = ({ shopId }) => {
  const [windowDays, setWindowDays] = useState(14)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)

  const fetchData = useCallback(async () => {
    if (!shopId) return
    setLoading(true)
    try {
      const res = await getRoiReport(shopId, { window_days: windowDays })
      if (res.code === 0) setData(res.data)
      else message.error(res.msg || '拉取失败')
    } catch (e) {
      message.error(e?.response?.data?.msg || '网络错误')
    } finally {
      setLoading(false)
    }
  }, [shopId, windowDays])

  useEffect(() => { fetchData() }, [fetchData])

  const totals = data?.totals
  const items = data?.items || []
  const empty = !totals || totals.total_applied === 0

  const columns = [
    {
      title: '商品',
      key: 'product',
      width: 200,
      render: (_, r) => (
        <Space size={6}>
          {r.image_url && <img src={r.image_url} alt="" style={{ width: 36, height: 36, objectFit: 'cover', borderRadius: 3 }} />}
          <Space direction="vertical" size={0}>
            <Text style={{ fontSize: 12 }}>{r.product_name || `ID ${r.product_id || '-'}`}</Text>
            <Text type="secondary" style={{ fontSize: 11 }}>SKU {r.platform_sku_id || '—'}</Text>
          </Space>
        </Space>
      ),
    },
    {
      title: '应用时间',
      dataIndex: 'applied_at',
      width: 140,
      render: (v, r) => (
        <Space direction="vertical" size={0}>
          <Text style={{ fontSize: 12 }}>{v ? new Date(v).toLocaleDateString('zh-CN') : '-'}</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>{r.applied_days_ago} 天前</Text>
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 130,
      render: (s, r) => {
        const m = STATUS_META[s] || STATUS_META.observing
        if (s === 'observing') {
          const pct = Math.round(r.after_days_elapsed / windowDays * 100)
          return (
            <Space direction="vertical" size={2}>
              <Tag icon={<ClockCircleOutlined />} color={m.color}>{m.label}</Tag>
              <Progress percent={pct} size="small" showInfo={false} strokeColor="#1890ff" style={{ margin: 0, width: 100 }} />
              <Text type="secondary" style={{ fontSize: 11 }}>{r.after_days_elapsed}/{windowDays} 天</Text>
            </Space>
          )
        }
        return <Tag color={m.color}>{m.label}</Tag>
      },
    },
    {
      title: `前 ${windowDays} 天`,
      key: 'before',
      width: 140,
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <Text style={{ fontSize: 12 }}>曝光 {r.before.impressions.toLocaleString()}</Text>
          <Text style={{ fontSize: 12 }}>订单 {r.before.orders} · ₽{Number(r.before.revenue).toFixed(0)}</Text>
        </Space>
      ),
    },
    {
      title: `后 ${windowDays} 天`,
      key: 'after',
      width: 140,
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <Text style={{ fontSize: 12 }}>曝光 {r.after.impressions.toLocaleString()}</Text>
          <Text style={{ fontSize: 12 }}>订单 {r.after.orders} · ₽{Number(r.after.revenue).toFixed(0)}</Text>
        </Space>
      ),
    },
    {
      title: '曝光变化',
      key: 'imp_delta',
      width: 100,
      align: 'right',
      render: (_, r) => <DeltaPct pct={r.delta.impressions_pct} />,
    },
    {
      title: '订单变化',
      key: 'ord_delta',
      width: 100,
      align: 'right',
      render: (_, r) => <DeltaPct pct={r.delta.orders_pct} />,
    },
    {
      title: '营收变化',
      key: 'rev_delta',
      width: 100,
      align: 'right',
      render: (_, r) => <DeltaPct pct={r.delta.revenue_pct} />,
    },
    {
      title: '标题同步',
      dataIndex: 'title_changed_to_generated',
      width: 110,
      render: (v) => v ? <Tag color="success">已同步</Tag> : <Tooltip title="当前平台标题与 AI 生成的不一致，可能用户没真改或被其他操作覆盖"><Tag color="warning">不一致</Tag></Tooltip>,
    },
  ]

  return (
    <>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="什么是 Before/After ROI 对比？"
        description={
          <Space direction="vertical" size={2}>
            <Text style={{ fontSize: 12 }}>
              以「AI 生成历史」Tab 中点过「标记已用」的时间为切割点，对比改标题前后 {windowDays} 天的曝光/订单/营收。
            </Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              • 「观察中」：改标题后天数不足 {windowDays} 天，数据还在回流
              • 「观察完成」：已满 {windowDays} 天，数据可靠
              • 数据源：Ozon Premium / WB Jam 搜索词每日统计（product_search_queries）
            </Text>
          </Space>
        }
      />

      <Space size={12} style={{ marginBottom: 12 }}>
        <Text style={{ fontSize: 13 }}>对比窗口：</Text>
        <Segmented
          value={windowDays}
          onChange={setWindowDays}
          options={[
            { label: '7 天', value: 7 },
            { label: '14 天', value: 14 },
            { label: '30 天', value: 30 },
          ]}
        />
        <Button icon={<SyncOutlined />} onClick={fetchData}>刷新</Button>
      </Space>

      {empty ? (
        <Alert
          type="warning"
          showIcon
          message="暂无已应用的 AI 标题记录"
          description={
            <Space direction="vertical" size={2}>
              <Text>{data?.empty_hint || '请先去「AI 生成历史」Tab，把改过标题的记录点「标记已用」。'}</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                建议：改 3-5 个商品标题并标记 → 等待 {windowDays} 天数据回流 → 在这里查看效果对比。
              </Text>
            </Space>
          }
        />
      ) : (
        <>
          <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
            <Col xs={12} sm={6}>
              <Card size="small" style={statCardStyle} bodyStyle={{ padding: 12 }}>
                <Statistic title="已应用商品" value={totals.total_applied}
                  suffix={<Text type="secondary" style={{ fontSize: 12 }}>个</Text>} />
                <Text type="secondary" style={{ fontSize: 11 }}>
                  完成 {totals.completed} · 观察中 {totals.observing}
                </Text>
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card size="small" style={statCardStyle} bodyStyle={{ padding: 12 }}>
                <Statistic
                  title="曝光合计变化"
                  value={totals.sum_impressions_after - totals.sum_impressions_before}
                  prefix={<EyeOutlined style={{ color: '#1890ff' }} />}
                  valueStyle={{ color: totals.sum_impressions_after >= totals.sum_impressions_before ? '#3f8600' : '#cf1322' }}
                />
                <Text type="secondary" style={{ fontSize: 11 }}>
                  前 {totals.sum_impressions_before} → 后 {totals.sum_impressions_after}
                </Text>
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card size="small" style={statCardStyle} bodyStyle={{ padding: 12 }}>
                <Statistic
                  title="订单合计变化"
                  value={totals.sum_orders_after - totals.sum_orders_before}
                  prefix={<ShoppingCartOutlined style={{ color: '#52c41a' }} />}
                  valueStyle={{ color: totals.sum_orders_after >= totals.sum_orders_before ? '#3f8600' : '#cf1322' }}
                />
                <Text type="secondary" style={{ fontSize: 11 }}>
                  前 {totals.sum_orders_before} → 后 {totals.sum_orders_after}
                </Text>
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card size="small" style={statCardStyle} bodyStyle={{ padding: 12 }}>
                <Statistic
                  title="平均曝光变化率"
                  value={totals.avg_impressions_delta_pct !== null ? totals.avg_impressions_delta_pct : '—'}
                  suffix={totals.avg_impressions_delta_pct !== null ? '%' : ''}
                  prefix={<DollarOutlined style={{ color: '#fa8c16' }} />}
                  valueStyle={{ color: (totals.avg_impressions_delta_pct || 0) >= 0 ? '#3f8600' : '#cf1322' }}
                />
                <Text type="secondary" style={{ fontSize: 11 }}>含零基线商品除外</Text>
              </Card>
            </Col>
          </Row>

          <Paragraph type="secondary" style={{ fontSize: 12 }}>
            每行一个「标记已用」记录。标题不一致 = 当前平台标题与 AI 生成的不符，可能用户没真改或被后续编辑覆盖。
          </Paragraph>

          <Table
            rowKey="generated_id"
            size="small"
            loading={loading}
            dataSource={items}
            columns={columns}
            pagination={false}
            scroll={{ x: 1100 }}
          />
        </>
      )}
    </>
  )
}

export default RoiReportTab
