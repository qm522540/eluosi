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
        <Space size={4}>
          {r.image_url && (
            <img src={r.image_url} alt="" style={{ width: 28, height: 28, objectFit: 'cover', borderRadius: 2 }} />
          )}
          <Tooltip title={r.current_title || v}>
            <span>{v}</span>
          </Tooltip>
        </Space>
      ),
    },
    {
      title: '来源',
      dataIndex: 'sources',
      key: 'sources',
      width: 200,
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
      width: 100,
      sorter: (a, b) => (a.score || 0) - (b.score || 0),
      render: (v) => <Tag color={scoreColor(v || 0)} style={{ fontSize: 13, minWidth: 36, textAlign: 'center' }}>{(v || 0).toFixed(1)}</Tag>,
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
      scroll={{ x: 1200 }}
    />
  )
}

export default SeoCandidatesTable
