import { useState, useEffect } from 'react'
import {
  Typography, Card, Table, Tag, Row, Col, Statistic, Alert, Empty, Badge, Progress,
} from 'antd'
import {
  ArrowUpOutlined, ArrowDownOutlined, MinusOutlined,
} from '@ant-design/icons'
import { getBudgetOverview, getBudgetSuggestions } from '@/api/ads'
import { PLATFORMS, AD_STATUS } from '@/utils/constants'

const { Text } = Typography

const AdsBudget = ({ shopId, platform, searched }) => {
  const [budgetData, setBudgetData] = useState(null)
  const [budgetLoading, setBudgetLoading] = useState(false)
  const [suggestions, setSuggestions] = useState([])
  const [suggestionsLoading, setSuggestionsLoading] = useState(false)

  const fetchBudget = async () => {
    setBudgetLoading(true)
    try {
      const params = {}
      if (shopId) params.shop_id = shopId
      if (platform) params.platform = platform
      const res = await getBudgetOverview(params)
      setBudgetData(res.data)
    } catch {
      setBudgetData(null)
    } finally {
      setBudgetLoading(false)
    }
  }

  const fetchBudgetSuggestions = async () => {
    setSuggestionsLoading(true)
    try {
      const params = {}
      if (shopId) params.shop_id = shopId
      if (platform) params.platform = platform
      const res = await getBudgetSuggestions(params)
      setSuggestions(res.data || [])
    } catch {
      setSuggestions([])
    } finally {
      setSuggestionsLoading(false)
    }
  }

  useEffect(() => {
    if (searched) {
      fetchBudget()
      fetchBudgetSuggestions()
    }
  }, [searched, shopId, platform])

  if (!searched) {
    return <Card><Empty description="请选择平台和店铺后点击确定" /></Card>
  }

  return (
    <>
      {/* 预算汇总 */}
      {budgetData?.summary && (
        <Row gutter={16} style={{ marginBottom: 24 }}>
          <Col span={5}>
            <Card size="small" loading={budgetLoading}>
              <Statistic title="总日预算" value={budgetData.summary.total_daily_budget} prefix="₽" precision={0} />
            </Card>
          </Col>
          <Col span={5}>
            <Card size="small" loading={budgetLoading}>
              <Statistic title="今日花费" value={budgetData.summary.total_today_spend} prefix="₽" precision={2}
                valueStyle={{ color: '#ff7875' }} />
            </Card>
          </Col>
          <Col span={5}>
            <Card size="small" loading={budgetLoading}>
              <Statistic title="本月花费" value={budgetData.summary.total_month_spend} prefix="₽" precision={2} />
            </Card>
          </Col>
          <Col span={5}>
            <Card size="small" loading={budgetLoading}>
              <Statistic title="预算使用率" value={budgetData.summary.budget_usage_pct} suffix="%"
                valueStyle={{ color: budgetData.summary.budget_usage_pct >= 80 ? '#ff4d4f' : '#52c41a' }} />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small" loading={budgetLoading}>
              <Statistic title="活跃活动" value={budgetData.summary.active_campaigns}
                suffix={`/ ${budgetData.summary.total_campaigns}`} />
            </Card>
          </Col>
        </Row>
      )}

      {/* 预算预警 */}
      {budgetData?.alerts?.length > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={`${budgetData.alerts.length} 个活动预算使用率较高`}
          description={
            <ul style={{ margin: '8px 0', paddingLeft: 20 }}>
              {budgetData.alerts.map((a, i) => (
                <li key={a.campaign_id || i}>
                  <Tag color={a.level === 'critical' ? 'red' : 'orange'}>{a.level === 'critical' ? '超标' : '预警'}</Tag>
                  {a.name}: {a.message}（今日 ₽{a.today_spend} / 预算 ₽{a.daily_budget}）
                </li>
              ))}
            </ul>
          }
        />
      )}

      {/* 活动预算明细 */}
      <Card title="活动预算消耗明细" size="small" style={{ marginBottom: 24 }}>
        <Table size="small" dataSource={budgetData?.campaigns || []} rowKey="campaign_id" loading={budgetLoading}
          pagination={{ pageSize: 10, size: 'small' }}
          columns={[
            { title: '活动名称', dataIndex: 'name', ellipsis: true },
            { title: '平台', dataIndex: 'platform', width: 100, render: p => <Tag color={PLATFORMS[p]?.color}>{PLATFORMS[p]?.label}</Tag> },
            { title: '日预算', dataIndex: 'daily_budget', width: 100, render: v => v ? `₽${v}` : '不限' },
            { title: '今日花费', dataIndex: 'today_spend', width: 100, render: v => `₽${v}` },
            {
              title: '使用率', dataIndex: 'budget_usage_pct', width: 140,
              render: v => v > 0 ? (
                <Progress percent={Math.min(v, 100)} size="small"
                  strokeColor={v >= 100 ? '#ff4d4f' : v >= 80 ? '#faad14' : '#52c41a'}
                  format={() => `${v}%`}
                />
              ) : '-',
            },
            { title: '均日消耗', dataIndex: 'avg_daily_spend', width: 100, render: v => `₽${v}` },
            { title: '本月花费', dataIndex: 'month_spend', width: 100, render: v => `₽${v}` },
            {
              title: '剩余天数', dataIndex: 'days_remaining', width: 90,
              render: v => v != null ? (
                <Text style={{ color: v <= 3 ? '#ff4d4f' : v <= 7 ? '#faad14' : '#52c41a' }}>{v}天</Text>
              ) : '-',
            },
            {
              title: '状态', dataIndex: 'status', width: 80,
              render: s => <Badge color={AD_STATUS[s]?.color} text={AD_STATUS[s]?.label || s} />,
            },
          ]}
        />
      </Card>

      {/* 预算优化建议 */}
      <Card title="预算分配优化建议" size="small" loading={suggestionsLoading}>
        {suggestions.length > 0 ? (
          <Table size="small" dataSource={suggestions} rowKey="campaign_id" pagination={false}
            columns={[
              { title: '活动名称', dataIndex: 'name', ellipsis: true },
              { title: '平台', dataIndex: 'platform', width: 100, render: p => <Tag color={PLATFORMS[p]?.color}>{PLATFORMS[p]?.label}</Tag> },
              { title: '当前预算', dataIndex: 'current_daily_budget', width: 100, render: v => v ? `₽${v}` : '不限' },
              {
                title: '建议预算', dataIndex: 'suggested_budget', width: 100,
                render: (v, r) => (
                  <Text style={{ color: r.action === 'increase' ? '#52c41a' : r.action === 'decrease' ? '#ff4d4f' : '#999' }}>
                    ₽{v}
                  </Text>
                ),
              },
              {
                title: '建议', dataIndex: 'action', width: 80,
                render: v => v === 'increase'
                  ? <Tag color="green" icon={<ArrowUpOutlined />}>加预算</Tag>
                  : v === 'decrease'
                    ? <Tag color="red" icon={<ArrowDownOutlined />}>降预算</Tag>
                    : <Tag icon={<MinusOutlined />}>维持</Tag>,
              },
              { title: '7日ROAS', dataIndex: 'roas_7d', width: 90, render: v => <Text style={{ color: v >= 1 ? '#52c41a' : '#ff4d4f' }}>{v}x</Text> },
              { title: '原因', dataIndex: 'reason', ellipsis: true },
            ]}
          />
        ) : <Empty description="暂无预算优化建议" />}
      </Card>
    </>
  )
}

export default AdsBudget
