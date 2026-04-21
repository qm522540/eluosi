import { Row, Col, Card, Statistic } from 'antd'
import { EyeOutlined, ShoppingCartOutlined, WarningOutlined, RiseOutlined } from '@ant-design/icons'

const cardStyle = {
  background: '#fafbff',
  borderColor: '#e6edff',
}

const TrackingStatsCards = ({ totals, period }) => {
  if (!totals) return null
  const days = period?.days || 7

  return (
    <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
      <Col xs={12} sm={6}>
        <Card size="small" style={cardStyle} bodyStyle={{ padding: 12 }}>
          <Statistic
            title={`本期（近${days}天）曝光`}
            value={totals.sum_impressions_cur || 0}
            prefix={<EyeOutlined style={{ color: '#1890ff' }} />}
          />
        </Card>
      </Col>
      <Col xs={12} sm={6}>
        <Card size="small" style={cardStyle} bodyStyle={{ padding: 12 }}>
          <Statistic
            title={`本期订单`}
            value={totals.sum_orders_cur || 0}
            prefix={<ShoppingCartOutlined style={{ color: '#52c41a' }} />}
          />
        </Card>
      </Col>
      <Col xs={12} sm={6}>
        <Card size="small" style={cardStyle} bodyStyle={{ padding: 12 }}>
          <Statistic
            title="下滑预警词"
            value={totals.drop_alert_count || 0}
            valueStyle={{ color: totals.drop_alert_count > 0 ? '#fa541c' : '#999' }}
            prefix={<WarningOutlined style={{ color: '#fa8c16' }} />}
          />
        </Card>
      </Col>
      <Col xs={12} sm={6}>
        <Card size="small" style={cardStyle} bodyStyle={{ padding: 12 }}>
          <Statistic
            title="本期新增核心词"
            value={totals.new_count || 0}
            valueStyle={{ color: totals.new_count > 0 ? '#52c41a' : '#999' }}
            prefix={<RiseOutlined style={{ color: '#52c41a' }} />}
          />
        </Card>
      </Col>
    </Row>
  )
}

export default TrackingStatsCards
