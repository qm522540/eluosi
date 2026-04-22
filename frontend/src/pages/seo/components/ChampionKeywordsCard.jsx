import { useState, useEffect } from 'react'
import { Card, Row, Col, Typography, Tag, Space, Empty, Skeleton, Tooltip } from 'antd'
import { FireOutlined, ArrowRightOutlined } from '@ant-design/icons'
import { getChampionKeywords } from '@/api/seo'

const { Text } = Typography

/**
 * 全店爆款词发现卡 — 置顶展示"跨商品爆款词 Top N"。
 *
 * 数据源：GET /seo/shop/{id}/champion-keywords
 * 筛选条件：带订单 + in_title=0 + in_attrs=0 + 至少 2 个商品
 *
 * Props:
 *   shopId         当前店铺 id
 *   onPickKeyword  点击某个爆款词的回调 → 父组件触发 keyword 筛选
 */
const ChampionKeywordsCard = ({ shopId, onPickKeyword }) => {
  const [loading, setLoading] = useState(false)
  const [items, setItems] = useState([])

  useEffect(() => {
    if (!shopId) { setItems([]); return }
    setLoading(true)
    getChampionKeywords(shopId, { limit: 6, min_products: 2 })
      .then(r => {
        if (r.code === 0) setItems(r.data?.items || [])
        else setItems([])
      })
      .catch(() => setItems([]))
      .finally(() => setLoading(false))
  }, [shopId])

  const title = (
    <Space>
      <FireOutlined style={{ color: '#fa541c' }} />
      <span>全店爆款词 · 改一个词多商品受益</span>
      <Tooltip title="这些词同时出现在多个商品的候选池里，都带过真实订单、但所有商品的俄语标题都没写它们。最大价值的批量改动机会。">
        <Text type="secondary" style={{ fontSize: 12, cursor: 'help' }}>?</Text>
      </Tooltip>
    </Space>
  )

  if (!loading && items.length === 0) {
    return null  // 没爆款词就完全不渲染，不占空间
  }

  return (
    <Card
      size="small"
      title={title}
      style={{
        marginBottom: 16,
        background: 'linear-gradient(to right, #fff7e6 0%, #fffbf0 100%)',
        border: '1px solid #ffd591',
      }}
    >
      {loading ? (
        <Skeleton active paragraph={{ rows: 2 }} />
      ) : (
        <Row gutter={[12, 12]}>
          {items.map((it, i) => (
            <Col xs={24} sm={12} lg={8} key={i}>
              <Card
                hoverable
                size="small"
                onClick={() => onPickKeyword && onPickKeyword(it.keyword)}
                style={{ border: '1px solid #ffe7ba' }}
                bodyStyle={{ padding: 10 }}
              >
                <div style={{ marginBottom: 6 }}>
                  <Text strong style={{ fontSize: 14, color: '#d4380d' }}>
                    {it.keyword}
                  </Text>
                </div>
                <Space size={4} wrap style={{ marginBottom: 6 }}>
                  <Tooltip title={`真实贡献商品数（真给订单过的） / 推荐覆盖商品数（含类目扩散推荐）`}>
                    <Tag color="blue" style={{ margin: 0, cursor: 'help' }}>
                      真 {it.self_product_count ?? it.product_count}
                      <Text type="secondary" style={{ fontSize: 10, margin: '0 2px' }}>/</Text>
                      推 {it.product_count}
                      <Text type="secondary" style={{ fontSize: 10, marginLeft: 2 }}>商品</Text>
                    </Tag>
                  </Tooltip>
                  <Tag color="red" style={{ margin: 0 }}>
                    {it.total_orders} 单
                  </Tag>
                  <Tag style={{ margin: 0 }}>
                    {it.total_impressions} 曝光
                  </Tag>
                </Space>
                {it.top_product_names?.length > 0 && (
                  <div style={{ color: '#999', fontSize: 11, lineHeight: 1.4 }}>
                    例：{it.top_product_names.slice(0, 2).join(' / ')}
                    {it.product_count > 2 && ` 等 ${it.product_count} 个`}
                  </div>
                )}
                <div style={{ marginTop: 6, textAlign: 'right' }}>
                  <Text style={{ fontSize: 11, color: '#fa541c' }}>
                    点击查看涉及商品 <ArrowRightOutlined />
                  </Text>
                </div>
              </Card>
            </Col>
          ))}
        </Row>
      )}
    </Card>
  )
}

export default ChampionKeywordsCard
