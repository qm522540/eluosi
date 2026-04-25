import { useState, useCallback } from 'react'
import { Table, Tag, Space, Typography, Tooltip, Progress, Button, message } from 'antd'
import { RobotOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { getProductMissingCandidates } from '@/api/seo'
import AiTitleModal from './AiTitleModal'

const { Text } = Typography

const SOURCE_TAG = {
  paid: { color: 'purple', label: '付费' },
  organic: { color: 'blue', label: '自然' },
  cross_shop: { color: 'orange', label: '跨店' },
  unknown: { color: 'default', label: '其他' },
}

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

  // 行展开状态：每个 pid 独立维护数据/loading/已勾选
  const [expandedKeys, setExpandedKeys] = useState([])
  const [expandedData, setExpandedData] = useState({})    // pid -> items[]
  const [expandedLoading, setExpandedLoading] = useState({}) // pid -> bool
  const [selectedByPid, setSelectedByPid] = useState({})  // pid -> selected rows

  // AiTitleModal 控制
  const [aiModal, setAiModal] = useState({
    open: false, productId: null, productName: '', currentTitle: '', selected: [],
  })

  const handleAiTitle = (pid) => {
    navigate(`/seo/optimize?shopId=${shopId}&productId=${pid}&autoAi=1`)
  }

  // 行展开：拉单商品全部缺词
  const onExpand = useCallback(async (expanded, record) => {
    const pid = record.product_id
    if (!expanded) {
      setExpandedKeys(prev => prev.filter(k => k !== pid))
      return
    }
    setExpandedKeys(prev => [...prev, pid])
    if (expandedData[pid]) return  // 已经拉过，不重复
    setExpandedLoading(prev => ({ ...prev, [pid]: true }))
    try {
      const res = await getProductMissingCandidates(shopId, pid)
      if (res.code === 0) {
        setExpandedData(prev => ({ ...prev, [pid]: res.data.items || [] }))
      } else {
        message.error(res.msg || '拉取失败')
      }
    } catch {
      message.error('拉取失败')
    } finally {
      setExpandedLoading(prev => ({ ...prev, [pid]: false }))
    }
  }, [shopId, expandedData])

  const openAiModal = (record) => {
    const pid = record.product_id
    const selected = selectedByPid[pid] || []
    if (!selected.length) {
      message.warning('请先勾选要融合的关键词')
      return
    }
    setAiModal({
      open: true,
      productId: pid,
      productName: record.product_name,
      currentTitle: record.current_title || '',
      selected: selected.map(s => ({ id: s.candidate_id, keyword: s.keyword })),
    })
  }

  // 嵌套表格列
  const expandedColumns = [
    {
      title: '来源', key: 'source', width: 80,
      render: (_, r) => {
        const meta = SOURCE_TAG[r.source_type] || SOURCE_TAG.unknown
        return <Tag color={meta.color} style={{ margin: 0 }}>{meta.label}</Tag>
      },
    },
    {
      title: '关键词', dataIndex: 'keyword', key: 'keyword',
      render: (v) => <Text style={{ fontSize: 12 }}>{v}</Text>,
    },
    {
      title: '来源店', key: 'src_shop', width: 120,
      render: (_, r) => r.cross_shop_name
        ? <Text style={{ fontSize: 11, color: '#fa8c16' }}>{r.cross_shop_name}</Text>
        : <Text type="secondary" style={{ fontSize: 11 }}>本店</Text>,
    },
    {
      title: '曝光', key: 'impr', width: 90, align: 'right',
      render: (_, r) => {
        const v = r.cross_frequency ?? r.organic_impressions
        return v != null ? <Text style={{ fontSize: 12 }}>{v.toLocaleString()}</Text> : <Text type="secondary">-</Text>
      },
    },
    {
      title: '订单', key: 'orders', width: 70, align: 'right',
      render: (_, r) => {
        const v = r.cross_orders ?? r.paid_orders ?? r.organic_orders
        return v != null ? <Text style={{ fontSize: 12 }}>{v}</Text> : <Text type="secondary">-</Text>
      },
    },
    {
      title: <Tooltip title="综合评分（多源命中加分 + ROAS + 订单/曝光对数加权）">推荐系数</Tooltip>,
      dataIndex: 'score', key: 'score', width: 90, align: 'right',
      render: (v) => {
        const s = Number(v) || 0
        const color = s >= 5 ? '#3f8600' : s >= 2 ? '#faad14' : '#999'
        return <Text strong style={{ color, fontSize: 12 }}>{s.toFixed(1)}</Text>
      },
    },
  ]

  const expandedRowRender = (record) => {
    const pid = record.product_id
    const items = expandedData[pid] || []
    const isLoading = !!expandedLoading[pid]
    const selectedKeys = (selectedByPid[pid] || []).map(s => s.candidate_id)
    return (
      <div style={{ background: '#fafafa', padding: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <Space>
            <Text strong style={{ fontSize: 13 }}>
              {record.product_name} · 全部缺词 {items.length} 个
            </Text>
            <Text type="secondary" style={{ fontSize: 11 }}>（按推荐系数降序，前 3 即"高价值词 Top 3"）</Text>
          </Space>
          <Button
            type="primary"
            size="small"
            icon={<ThunderboltOutlined />}
            disabled={!selectedKeys.length}
            onClick={() => openAiModal(record)}
          >
            用选中 {selectedKeys.length} 词生成新标题
          </Button>
        </div>
        <Table
          rowKey="candidate_id"
          size="small"
          loading={isLoading}
          dataSource={items}
          columns={expandedColumns}
          pagination={items.length > 20 ? { pageSize: 20, size: 'small' } : false}
          rowSelection={{
            selectedRowKeys: selectedKeys,
            onChange: (_keys, rows) => {
              setSelectedByPid(prev => ({ ...prev, [pid]: rows }))
            },
          }}
        />
      </div>
    )
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
      width: 360,
      render: (_, r) => {
        if (!r.missing_top_keywords?.length) {
          if (r.dimensions.coverage.data_insufficient) {
            return <Text type="secondary" style={{ fontSize: 12 }}>无候选数据 · 去优化建议点「刷新引擎」</Text>
          }
          return <Text type="success" style={{ fontSize: 12 }}>✓ 核心词已全部覆盖</Text>
        }
        // 来源分色：付费=紫 / 自然=蓝 / 跨店=橙 / 未知=火山
        const tagColorMap = {
          paid: 'purple',
          organic: 'blue',
          cross_shop: 'orange',
          unknown: 'volcano',
        }
        const tagLabelMap = {
          paid: '付费',
          organic: '自然',
          cross_shop: '跨店',
        }
        return (
          <Space size={4} direction="vertical" style={{ width: '100%' }}>
            {r.missing_top_keywords.map((k, i) => {
              const stype = k.source_type || 'unknown'
              const color = tagColorMap[stype] || 'volcano'
              const label = tagLabelMap[stype]
              return (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  {label && (
                    <Tag color={color} style={{ margin: 0, fontSize: 10, padding: '0 4px', lineHeight: '16px' }}>
                      {label}
                    </Tag>
                  )}
                  <Tag color={color} style={{ margin: 0 }}>{k.keyword}</Tag>
                  {k.metric && <Text type="secondary" style={{ fontSize: 11 }}>{k.metric}</Text>}
                </div>
              )
            })}
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
    <>
      <Table
        rowKey="product_id"
        size="small"
        loading={loading}
        dataSource={data || []}
        columns={columns}
        pagination={pagination}
        onChange={onPaginationChange}
        scroll={{ x: 1200 }}
        expandable={{
          expandedRowKeys: expandedKeys,
          onExpand,
          expandedRowRender,
          rowExpandable: (r) => !!r.candidate_count,  // 没候选数据的不能展开
        }}
      />
      <AiTitleModal
        open={aiModal.open}
        onClose={() => setAiModal(prev => ({ ...prev, open: false }))}
        shopId={shopId}
        productId={aiModal.productId}
        productName={aiModal.productName}
        currentTitle={aiModal.currentTitle}
        selectedCandidates={aiModal.selected}
      />
    </>
  )
}

export default HealthProductsTable
