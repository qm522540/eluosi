import { useState, useEffect } from 'react'
import { Table, Empty, Spin, Typography, Space, Tooltip } from 'antd'
import { KeyOutlined, InfoCircleOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { getProductSearchInsights } from '@/api/search_insights'

const { Text } = Typography

const SearchInsightsSection = ({ productId }) => {
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState(null)

  useEffect(() => {
    if (!productId) return
    setLoading(true)
    const params = {
      date_from: dayjs().subtract(30, 'day').format('YYYY-MM-DD'),
      date_to: dayjs().subtract(1, 'day').format('YYYY-MM-DD'),
      size: 50,
    }
    getProductSearchInsights(productId, params)
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [productId])

  const items = data?.items || []

  const columns = [
    {
      title: '关键词', dataIndex: 'query_text', key: 'query_text',
      ellipsis: true,
      render: v => <Text strong>{v}</Text>,
    },
    {
      title: <Tooltip title="搜索次数 = 该商品在搜索结果列表中出现的累计次数（WB frequency / Ozon unique_search_users，SKU 级字段）。">
        搜索次数 <InfoCircleOutlined style={{ color: '#999' }} />
      </Tooltip>,
      dataIndex: 'frequency', key: 'frequency',
      width: 100, align: 'right',
      render: v => (v || 0).toLocaleString(),
    },
    {
      title: <Tooltip title="曝光 = 用户搜词后真正滚动看见该商品卡片的次数（WB 不返此字段为 0；Ozon unique_view_users）。恒有 曝光 ≤ 搜索次数。">
        曝光 <InfoCircleOutlined style={{ color: '#999' }} />
      </Tooltip>,
      dataIndex: 'impressions', key: 'impressions',
      width: 90, align: 'right',
      render: v => (v || 0).toLocaleString(),
    },
    {
      title: <Tooltip title="曝光比例 = 曝光 / 搜索次数。反映该商品在搜索列表里被翻到的程度。">
        曝光比例 <InfoCircleOutlined style={{ color: '#999' }} />
      </Tooltip>,
      key: 'view_rate', width: 100, align: 'right',
      render: (_, r) => {
        if (!r.frequency) return '-'
        const pct = r.impressions / r.frequency * 100
        let color = '#f5222d'
        if (pct >= 60) color = '#52c41a'
        else if (pct >= 30) color = '#faad14'
        return <Text style={{ color, fontWeight: 500 }}>{pct.toFixed(0)}%</Text>
      },
    },
    { title: '点击', dataIndex: 'clicks', key: 'clicks', width: 80, align: 'right' },
    { title: '加购', dataIndex: 'add_to_cart', key: 'add_to_cart', width: 80, align: 'right' },
    { title: '下单', dataIndex: 'orders', key: 'orders', width: 80, align: 'right' },
    {
      title: '销售额(₽)', dataIndex: 'revenue', key: 'revenue',
      width: 110, align: 'right',
      render: v => (v || 0).toFixed(2),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 8 }}>
        <Space size={6}>
          <KeyOutlined style={{ color: '#1677ff' }} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            用户搜哪些词找到该商品 · 近 30 天 · 需店铺开通 Jam/Premium 后「同步数据」才有
          </Text>
        </Space>
      </div>
      <Spin spinning={loading}>
        {items.length > 0 ? (
          <Table
            rowKey="query_text"
            columns={columns}
            dataSource={items}
            size="small"
            pagination={{ pageSize: 10, size: 'small' }}
            scroll={{ x: 720 }}
          />
        ) : (
          <Empty
            description={
              loading
                ? '加载中...'
                : '暂无数据（该商品未同步过搜索词 / 店铺未开通订阅）'
            }
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            style={{ padding: '24px 0' }}
          />
        )}
      </Spin>
    </div>
  )
}

export default SearchInsightsSection
