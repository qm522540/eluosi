import { Row, Col, Card, Statistic } from 'antd'
import {
  KeyOutlined, DollarOutlined, FireOutlined, ShoppingOutlined,
} from '@ant-design/icons'

const SeoStatsCards = ({ totals }) => {
  const t = totals || {}
  return (
    <Row gutter={16} style={{ marginBottom: 16 }}>
      <Col xs={12} md={6}>
        <Card size="small">
          <Statistic
            title="候选词总数"
            value={t.total || 0}
            prefix={<KeyOutlined />}
          />
        </Card>
      </Col>
      <Col xs={12} md={6}>
        <Card size="small">
          <Statistic
            title="已有付费转化"
            value={t.with_conversion || 0}
            valueStyle={{ color: '#3f8600' }}
            prefix={<DollarOutlined />}
          />
        </Card>
      </Col>
      <Col xs={12} md={6}>
        <Card size="small">
          <Statistic
            title="高价值缺口词"
            value={t.gap || 0}
            valueStyle={{ color: '#cf1322' }}
            prefix={<FireOutlined />}
            suffix={<span style={{ fontSize: 12, color: '#999' }}>需优化</span>}
          />
        </Card>
      </Col>
      <Col xs={12} md={6}>
        <Card size="small">
          <Statistic
            title="可反哺商品"
            value={t.products || 0}
            prefix={<ShoppingOutlined />}
          />
        </Card>
      </Col>
    </Row>
  )
}

export default SeoStatsCards
