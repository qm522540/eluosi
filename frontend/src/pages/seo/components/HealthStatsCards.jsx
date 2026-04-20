import { Row, Col, Card, Statistic } from 'antd'
import {
  DashboardOutlined, WarningOutlined, InfoCircleOutlined, CheckCircleOutlined,
} from '@ant-design/icons'

const HealthStatsCards = ({ totals }) => {
  const t = totals || {}
  return (
    <Row gutter={16} style={{ marginBottom: 16 }}>
      <Col xs={12} md={6}>
        <Card size="small">
          <Statistic
            title="全店平均分"
            value={t.avg_score || 0}
            precision={1}
            prefix={<DashboardOutlined />}
            suffix={<span style={{ fontSize: 12, color: '#999' }}>/ 100</span>}
          />
        </Card>
      </Col>
      <Col xs={12} md={6}>
        <Card size="small">
          <Statistic
            title="差 (< 40)"
            value={t.poor || 0}
            valueStyle={{ color: '#cf1322' }}
            prefix={<WarningOutlined />}
            suffix={<span style={{ fontSize: 12, color: '#999' }}>优先优化</span>}
          />
        </Card>
      </Col>
      <Col xs={12} md={6}>
        <Card size="small">
          <Statistic
            title="中 (40-70)"
            value={t.fair || 0}
            valueStyle={{ color: '#faad14' }}
            prefix={<InfoCircleOutlined />}
          />
        </Card>
      </Col>
      <Col xs={12} md={6}>
        <Card size="small">
          <Statistic
            title="优 (≥ 70)"
            value={t.good || 0}
            valueStyle={{ color: '#3f8600' }}
            prefix={<CheckCircleOutlined />}
          />
        </Card>
      </Col>
    </Row>
  )
}

export default HealthStatsCards
