import { Table, Tag, Space, Typography, Tooltip, Progress, Button } from 'antd'
import { RobotOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'

const { Text } = Typography

const GRADE_META = {
  poor: { color: '#cf1322', bg: '#fff1f0', label: '差' },
  fair: { color: '#faad14', bg: '#fffbe6', label: '中' },
  good: { color: '#3f8600', bg: '#f6ffed', label: '优' },
}

const ScoreBig = ({ score, grade }) => {
  const meta = GRADE_META[grade] || GRADE_META.fair
  return (
    <Tooltip title={`${meta.label}等 · 点击旁边按钮跳到 AI 优化`}>
      <div style={{
        display: 'inline-block',
        minWidth: 52,
        padding: '4px 8px',
        textAlign: 'center',
        background: '#fafbff',
        border: '1px solid #e6edff',
        borderRadius: 4,
      }}>
        <div style={{ fontSize: 16, fontWeight: 600, color: meta.color, lineHeight: 1.2 }}>
          {score.toFixed(1)}
        </div>
        <div style={{ fontSize: 11, color: '#999' }}>{meta.label}等</div>
      </div>
    </Tooltip>
  )
}

const DimensionBar = ({ label, detail }) => {
  if (detail.data_insufficient) {
    return (
      <Tooltip title={detail.hint || '该维度无可用数据，已从评分中豁免'}>
        <div style={{ marginBottom: 2 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#999' }}>
            <span>{label}</span>
            <span style={{ fontStyle: 'italic' }}>无数据 · 已豁免</span>
          </div>
          <div style={{ height: 6, background: '#f5f5f5', borderRadius: 3, marginTop: 2 }} />
        </div>
      </Tooltip>
    )
  }
  const pct = Math.round((detail.score / detail.weight) * 100)
  const color = pct >= 70 ? '#52c41a' : (pct >= 40 ? '#faad14' : '#ff4d4f')
  return (
    <Tooltip title={detail.hint || ''}>
      <div style={{ marginBottom: 2 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#666' }}>
          <span>{label}</span>
          <span>{detail.score} / {detail.weight}</span>
        </div>
        <Progress
          percent={pct}
          size="small"
          showInfo={false}
          strokeColor={color}
        />
      </div>
    </Tooltip>
  )
}

const HealthProductsTable = ({
  shopId, data, loading, pagination, onPaginationChange,
}) => {
  const navigate = useNavigate()

  const handleAiTitle = (pid) => {
    navigate(`/seo/optimize?shopId=${shopId}&productId=${pid}&autoAi=1`)
  }

  const columns = [
    {
      title: '商品',
      key: 'product',
      width: 260,
      render: (_, r) => (
        <Space size={8}>
          {r.image_url
            ? <img src={r.image_url} alt="" style={{ width: 40, height: 40, objectFit: 'cover', borderRadius: 2 }} />
            : <div style={{ width: 40, height: 40, background: '#f5f5f5', borderRadius: 2 }} />
          }
          <div>
            <Tooltip title={r.current_title}>
              <div style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {r.product_name || <Text type="secondary">（无名）</Text>}
              </div>
            </Tooltip>
            <Text type="secondary" style={{ fontSize: 11 }}>
              ID {r.product_id} · {r.platform?.toUpperCase()}
            </Text>
          </div>
        </Space>
      ),
    },
    {
      title: 'SEO 分',
      key: 'score',
      width: 90,
      align: 'center',
      sorter: true,
      render: (_, r) => <ScoreBig score={r.score} grade={r.grade} />,
    },
    {
      title: '分维度',
      key: 'dimensions',
      width: 240,
      render: (_, r) => (
        <div>
          <DimensionBar label="候选词覆盖" detail={r.dimensions.coverage} />
          <DimensionBar label="标题长度" detail={r.dimensions.title_length} />
          <DimensionBar label="商品评分" detail={r.dimensions.rating} />
        </div>
      ),
    },
    {
      title: '缺的高价值词 Top 3',
      key: 'missing',
      width: 320,
      render: (_, r) => {
        if (!r.missing_top_keywords?.length) {
          if (r.dimensions.coverage.data_insufficient) {
            return <Text type="secondary" style={{ fontSize: 12 }}>无候选数据 · 去优化建议点「刷新引擎」</Text>
          }
          return <Text type="success" style={{ fontSize: 12 }}>✓ 核心词已全部覆盖</Text>
        }
        return (
          <Space size={4} direction="vertical" style={{ width: '100%' }}>
            {r.missing_top_keywords.map((k, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Tag color="volcano" style={{ margin: 0 }}>{k.keyword}</Tag>
                {k.metric && <Text type="secondary" style={{ fontSize: 11 }}>{k.metric}</Text>}
              </div>
            ))}
          </Space>
        )
      },
    },
    {
      title: '候选/已覆盖',
      key: 'cover',
      width: 100,
      align: 'center',
      render: (_, r) => (
        <div>
          <div><strong>{r.covered_count}</strong> / {r.candidate_count}</div>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {r.candidate_count ? Math.round(r.covered_count / r.candidate_count * 100) : 0}% 覆盖
          </Text>
        </div>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      fixed: 'right',
      render: (_, r) => (
        <Space direction="vertical" size={4}>
          <Button
            type="primary"
            size="small"
            icon={<RobotOutlined />}
            onClick={() => handleAiTitle(r.product_id)}
            disabled={!r.candidate_count}
          >
            AI 优化标题
          </Button>
          {!r.candidate_count && (
            <Text type="secondary" style={{ fontSize: 11 }}>先去刷新引擎</Text>
          )}
        </Space>
      ),
    },
  ]

  return (
    <Table
      rowKey="product_id"
      size="small"
      loading={loading}
      dataSource={data || []}
      columns={columns}
      pagination={pagination}
      onChange={onPaginationChange}
      scroll={{ x: 1200 }}
    />
  )
}

export default HealthProductsTable
