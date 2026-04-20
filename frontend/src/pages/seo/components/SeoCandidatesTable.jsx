import { Table, Tag, Button, Space, Typography, Tooltip, Badge } from 'antd'
import {
  CheckCircleFilled, CloseCircleOutlined, TagOutlined,
} from '@ant-design/icons'
import SourceBadges from './SourceBadges'

const { Text } = Typography

const STATUS_META = {
  pending:   { color: 'processing', text: '待处理' },
  adopted:   { color: 'success',    text: '已加入' },
  ignored:   { color: 'default',    text: '已忽略' },
  processed: { color: 'warning',    text: '已应用' },
}

const roasColor = (r) => (r == null ? '#999' : r >= 5 ? '#3f8600' : r >= 2 ? '#faad14' : '#cf1322')

const scoreColor = (s) => (s >= 8 ? 'green' : s >= 5 ? 'gold' : 'default')

const evidenceTier = (orders, impr) => {
  if (orders > 0) return { label: '强', color: '#52c41a', bg: '#f6ffed', border: '#b7eb8f', tip: '有真实订单证明这个词能带量' }
  if (impr >= 20) return { label: '中', color: '#faad14', bg: '#fffbe6', border: '#ffe58f', tip: '有曝光量但尚未转化，值得一试' }
  if (impr > 0) return { label: '弱', color: '#999', bg: '#fafafa', border: '#eee', tip: '曝光很少，证据不足' }
  return null
}

const CoverDot = ({ ok, label }) => (
  <Tooltip title={`${label}${ok ? '已覆盖' : '未覆盖'}`}>
    {ok
      ? <CheckCircleFilled style={{ color: '#52c41a', fontSize: 14 }} />
      : <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 14 }} />
    }
  </Tooltip>
)

const SeoCandidatesTable = ({
  data, loading,
  selectedKeys, onSelectChange,
  onAdopt, onIgnore,
  pagination, onPaginationChange,
  platform,
}) => {
  const showPaid = platform !== 'ozon'
  const columns = [
    {
      title: '关键词',
      dataIndex: 'keyword',
      key: 'keyword',
      width: 180,
      render: (v) => <Text copyable={{ text: v }} strong>{v}</Text>,
    },
    {
      title: '商品',
      dataIndex: 'product_name',
      key: 'product_name',
      width: 220,
      ellipsis: true,
      render: (v, r) => (
        <Space size={4} align="start">
          {r.image_url && (
            <img src={r.image_url} alt="" style={{ width: 28, height: 28, objectFit: 'cover', borderRadius: 2, marginTop: 2 }} />
          )}
          <div style={{ lineHeight: 1.3, minWidth: 0 }}>
            <Tooltip title={r.current_title || v}>
              <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{v}</div>
            </Tooltip>
            {r.product_code && (
              <div style={{ fontSize: 11, color: '#999' }}>{r.product_code}</div>
            )}
          </div>
        </Space>
      ),
    },
    {
      title: '来源',
      dataIndex: 'sources',
      key: 'sources',
      width: 100,
      render: (s) => <SourceBadges sources={s} />,
    },
    {
      title: (
        <Tooltip title="越高越值得优先改标题。计算方式：来源数×2 + ROAS + log(订单+1)×2 + log(曝光+1) + log(自然订单+1)×2">
          优先级分
        </Tooltip>
      ),
      dataIndex: 'score',
      key: 'score',
      width: 72,
      sorter: (a, b) => (a.score || 0) - (b.score || 0),
      render: (v) => <Tag color={scoreColor(v || 0)} style={{ fontSize: 11, minWidth: 28, textAlign: 'center', margin: 0 }}>{(v || 0).toFixed(1)}</Tag>,
    },
    {
      title: (
        <Tooltip
          overlayStyle={{ maxWidth: 360 }}
          title={(
            <div style={{ lineHeight: 1.6 }}>
              <div><strong>这个词在你店里的真实历史表现：</strong></div>
              <div>• <strong>曝光</strong>：用户搜这个词后，<u>你这个商品</u>出现在搜索结果里的次数（不是全网搜索量）</div>
              <div>• <strong>订单</strong>：用户搜这个词 → 点进你商品 → 最终下单的次数（平台按最后一次搜索词归因）</div>
              <div>• <strong>加购</strong>：搜这个词进来后加了购物车但未必下单</div>
              <div style={{ marginTop: 4, color: '#ffd591' }}>
                有订单 = 强证据（这个词真能带成交，最该优先改标题）。Ozon 店订单基本都是自然搜索来的（付费广告 API 不做关键词级归因）。
              </div>
            </div>
          )}
        >
          实证表现
        </Tooltip>
      ),
      key: 'evidence',
      width: 160,
      sorter: (a, b) => {
        const aOrd = (a.paid_orders || 0) + (a.organic_orders || 0)
        const bOrd = (b.paid_orders || 0) + (b.organic_orders || 0)
        if (aOrd !== bOrd) return aOrd - bOrd
        return (a.organic_impressions || 0) - (b.organic_impressions || 0)
      },
      render: (_, r) => {
        const orders = (r.paid_orders || 0) + (r.organic_orders || 0)
        const impr = r.organic_impressions || 0
        const tier = evidenceTier(orders, impr)
        if (!tier) return <Text type="secondary">-</Text>
        const badge = (
          <Tooltip title={tier.tip}>
            <span style={{
              display: 'inline-block',
              padding: '0 6px',
              marginRight: 6,
              fontSize: 11,
              lineHeight: '16px',
              color: tier.color,
              background: tier.bg,
              border: `1px solid ${tier.border}`,
              borderRadius: 3,
              fontWeight: 600,
            }}>{tier.label}</span>
          </Tooltip>
        )
        if (orders > 0) {
          return (
            <div style={{ lineHeight: 1.4 }}>
              <div>
                {badge}
                <span style={{ color: '#cf1322', fontWeight: 600 }}>订单 {orders}</span>
                <span style={{ color: '#888', fontSize: 12, marginLeft: 6 }}>曝光 {impr}</span>
              </div>
              {r.organic_add_to_cart > 0 && (
                <div style={{ color: '#999', fontSize: 11, marginLeft: 22 }}>加购 {r.organic_add_to_cart}</div>
              )}
            </div>
          )
        }
        return (
          <div style={{ lineHeight: 1.4 }}>
            <div>
              {badge}
              <span style={{ color: '#555' }}>曝光 <strong>{impr}</strong></span>
            </div>
            <div style={{ color: '#bbb', fontSize: 11, marginLeft: 22 }}>暂无订单</div>
          </div>
        )
      },
    },
    showPaid && {
      title: (
        <Tooltip title="从付费广告点击后搜到这个词的数据。仅 WB 店有，Ozon 店暂无（平台 API 限制）。">
          付费数据
        </Tooltip>
      ),
      key: 'paid',
      width: 200,
      render: (_, r) => {
        if (r.paid_orders == null && r.paid_roas == null) {
          return <Text type="secondary">-</Text>
        }
        return (
          <div style={{ lineHeight: 1.4 }}>
            <div style={{ color: roasColor(r.paid_roas) }}>
              ROAS <strong>{r.paid_roas?.toFixed(2) || '-'}</strong>
              <span style={{ color: '#999', marginLeft: 8 }}>订单 {r.paid_orders || 0}</span>
            </div>
            <div style={{ color: '#999', fontSize: 12 }}>
              花费 ¥{(r.paid_spend || 0).toFixed(0)} · 营收 ¥{(r.paid_revenue || 0).toFixed(0)}
            </div>
          </div>
        )
      },
    },
    {
      title: '覆盖',
      key: 'cover',
      width: 90,
      render: (_, r) => (
        <Space size={8}>
          <div>
            <CoverDot ok={r.in_title} label="标题" />
            <div style={{ fontSize: 11, color: '#999' }}>标题</div>
          </div>
          <div>
            <CoverDot ok={r.in_attrs} label="属性" />
            <div style={{ fontSize: 11, color: '#999' }}>属性</div>
          </div>
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (s) => {
        const m = STATUS_META[s] || STATUS_META.pending
        return <Badge status={m.color} text={m.text} />
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 160,
      fixed: 'right',
      render: (_, r) => (
        <Space size={4}>
          {r.status === 'pending' && (
            <>
              <Button size="small" type="link" icon={<TagOutlined />} onClick={() => onAdopt(r)}>
                加入标题
              </Button>
              <Button size="small" type="link" danger onClick={() => onIgnore([r.id])}>
                忽略
              </Button>
            </>
          )}
          {r.status === 'ignored' && (
            <Button size="small" type="link" onClick={() => onAdopt(r)}>
              重新加入
            </Button>
          )}
          {r.status === 'adopted' && (
            <Text type="success">✓ 已加入候选</Text>
          )}
        </Space>
      ),
    },
  ]

  return (
    <Table
      rowKey="id"
      size="small"
      loading={loading}
      dataSource={data || []}
      columns={columns.filter(Boolean)}
      rowSelection={{
        selectedRowKeys: selectedKeys,
        onChange: onSelectChange,
      }}
      pagination={pagination}
      onChange={onPaginationChange}
      scroll={{ x: 1400 }}
    />
  )
}

export default SeoCandidatesTable
