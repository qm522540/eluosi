import { Row, Col, Card, Statistic, Tooltip } from 'antd'
import {
  KeyOutlined, CheckCircleOutlined, FireOutlined, ShoppingOutlined,
} from '@ant-design/icons'

const SeoStatsCards = ({ totals, onSelectWithOrders, currentSource }) => {
  const t = totals || {}
  const isActive = currentSource === 'with_orders'

  const strongCardStyle = {
    cursor: 'pointer',
    border: isActive ? '2px solid #52c41a' : '1px solid #b7eb8f',
    background: isActive ? '#f6ffed' : '#fafffa',
  }

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
        <Tooltip title={isActive ? '当前正在查看强证据词，点击取消筛选' : '点击筛选：只看带真实订单的强证据词'}>
          <Card
            size="small"
            hoverable
            style={strongCardStyle}
            onClick={() => onSelectWithOrders && onSelectWithOrders(isActive ? 'all' : 'with_orders')}
          >
            <Statistic
              title={(
                <span>
                  ✅ 带真实订单（强证据）
                  {isActive && <span style={{ color: '#52c41a', marginLeft: 6, fontSize: 12 }}>· 已筛选</span>}
                </span>
              )}
              value={t.with_conversion || 0}
              valueStyle={{ color: '#3f8600' }}
              prefix={<CheckCircleOutlined />}
              suffix={<span style={{ fontSize: 12, color: '#999' }}>点击筛选</span>}
            />
          </Card>
        </Tooltip>
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
