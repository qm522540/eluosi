import { Card, Row, Col, Space, Tag, Typography, Button, Empty } from 'antd'
import { WarningOutlined, RiseOutlined, ArrowRightOutlined } from '@ant-design/icons'

const { Text } = Typography

const ALERT_LABEL = {
  vanish:      { color: '#cf1322', label: '曝光消失' },
  drop:        { color: '#fa541c', label: '曝光跌 ≥ 30%' },
  orders_drop: { color: '#fa8c16', label: '订单归零' },
}

/**
 * 今日看点摘要卡 — 一眼看到"该重点关注什么"
 * 左：下滑预警 Top 3；右：新爆款词 Top 3
 * 点词直接触发对应筛选（父组件处理）
 */
const TrackingInsightCard = ({ highlights, onFilterByKeyword, onSwitchAlertOnly, onSwitchNewOnly }) => {
  if (!highlights || !highlights.has_any) return null
  const { drop_top3 = [], new_top3 = [] } = highlights

  return (
    <Card
      size="small"
      style={{
        background: 'linear-gradient(120deg, #fff7e6 0%, #f6ffed 100%)',
        borderColor: '#ffd591',
        marginBottom: 12,
      }}
      bodyStyle={{ padding: 14 }}
    >
      <Row gutter={[16, 12]}>
        {/* 下滑预警 Top 3 */}
        <Col xs={24} md={12}>
          <Space direction="vertical" size={6} style={{ width: '100%' }}>
            <Space size={6}>
              <WarningOutlined style={{ color: '#fa541c', fontSize: 16 }} />
              <Text strong>下滑预警</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>（Top 3）</Text>
              {drop_top3.length > 0 && (
                <Button size="small" type="link" style={{ padding: 0, height: 20, fontSize: 12 }}
                  onClick={onSwitchAlertOnly}>
                  查看全部 <ArrowRightOutlined />
                </Button>
              )}
            </Space>
            {drop_top3.length === 0 ? (
              <Text type="secondary" style={{ fontSize: 12 }}>当前无下滑预警词</Text>
            ) : (
              drop_top3.map((it) => {
                const m = ALERT_LABEL[it.alert] || { color: '#999', label: it.alert }
                return (
                  <div
                    key={it.query_text}
                    onClick={() => onFilterByKeyword(it.query_text)}
                    style={{
                      cursor: 'pointer',
                      padding: '6px 8px',
                      background: '#fff',
                      borderRadius: 4,
                      border: '1px solid #ffe7ba',
                    }}
                  >
                    <Space size={6} style={{ width: '100%', justifyContent: 'space-between' }}>
                      <Text style={{ fontSize: 12 }}>{it.query_text}</Text>
                      <Space size={4}>
                        <Tag color={m.color.replace('#', '')} style={{ margin: 0, fontSize: 11 }}>
                          {m.label}
                        </Tag>
                        <Text type="secondary" style={{ fontSize: 11 }}>
                          {it.impressions_prev} → {it.impressions_cur}
                        </Text>
                      </Space>
                    </Space>
                  </div>
                )
              })
            )}
          </Space>
        </Col>

        {/* 新增词 Top 3 */}
        <Col xs={24} md={12}>
          <Space direction="vertical" size={6} style={{ width: '100%' }}>
            <Space size={6}>
              <RiseOutlined style={{ color: '#52c41a', fontSize: 16 }} />
              <Text strong>本期新增</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>（Top 3 按曝光）</Text>
              {new_top3.length > 0 && (
                <Button size="small" type="link" style={{ padding: 0, height: 20, fontSize: 12 }}
                  onClick={onSwitchNewOnly}>
                  查看全部 <ArrowRightOutlined />
                </Button>
              )}
            </Space>
            {new_top3.length === 0 ? (
              <Text type="secondary" style={{ fontSize: 12 }}>当前无新增核心词</Text>
            ) : (
              new_top3.map((it) => (
                <div
                  key={it.query_text}
                  onClick={() => onFilterByKeyword(it.query_text)}
                  style={{
                    cursor: 'pointer',
                    padding: '6px 8px',
                    background: '#fff',
                    borderRadius: 4,
                    border: '1px solid #b7eb8f',
                  }}
                >
                  <Space size={6} style={{ width: '100%', justifyContent: 'space-between' }}>
                    <Text style={{ fontSize: 12 }}>{it.query_text}</Text>
                    <Space size={4}>
                      <Tag color="green" style={{ margin: 0, fontSize: 11 }}>新</Tag>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        曝光 {it.impressions_cur} · 涉 {it.skus_involved} 商品
                      </Text>
                    </Space>
                  </Space>
                </div>
              ))
            )}
          </Space>
        </Col>
      </Row>
    </Card>
  )
}

export default TrackingInsightCard
