import { useState, useEffect, useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Typography, Card, Space, Select, Segmented, Input, Button, Table, Tag,
  message, Modal, Descriptions, Alert, Row, Col, Tabs,
} from 'antd'
import {
  CopyOutlined, CheckOutlined, SyncOutlined, LineChartOutlined, HistoryOutlined,
} from '@ant-design/icons'
import { getShops } from '@/api/shops'
import { getGeneratedTitles, applyGeneratedTitle } from '@/api/seo'
import RoiReportTab from './components/RoiReportTab'

const { Title, Text, Paragraph } = Typography
const { Option } = Select

const PLATFORM_LABEL = { wb: 'WB', ozon: 'Ozon' }

const STATUS_META = {
  pending:  { color: 'processing', label: '待用' },
  approved: { color: 'warning',    label: '已审' },
  applied:  { color: 'success',    label: '已应用' },
  rejected: { color: 'default',    label: '已拒' },
}

const Report = () => {
  const [searchParams] = useSearchParams()
  const [shops, setShops] = useState([])
  const [shopId, setShopId] = useState(null)
  const [approvalStatus, setApprovalStatus] = useState('all')
  const [keyword, setKeyword] = useState('')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)

  const [page, setPage] = useState(1)
  const [size, setSize] = useState(20)

  const [detailRow, setDetailRow] = useState(null)

  useEffect(() => {
    getShops({ page: 1, page_size: 100 })
      .then(r => {
        const items = (r.data?.items || []).filter(s => ['wb', 'ozon'].includes(s.platform))
        setShops(items)
        const urlShopId = Number(searchParams.get('shopId'))
        const preferId = urlShopId && items.find(s => s.id === urlShopId) ? urlShopId : (items[0]?.id || null)
        if (preferId && !shopId) setShopId(preferId)
      })
      .catch(() => setShops([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fetchData = useCallback(async () => {
    if (!shopId) return
    setLoading(true)
    try {
      const res = await getGeneratedTitles(shopId, {
        approval_status: approvalStatus, keyword: keyword.trim(), page, size,
      })
      if (res.code === 0) setData(res.data)
      else message.error(res.msg || '拉取失败')
    } catch (e) {
      message.error(e?.response?.data?.msg || '网络错误')
    } finally {
      setLoading(false)
    }
  }, [shopId, approvalStatus, keyword, page, size])

  useEffect(() => { fetchData() }, [fetchData])

  const handleCopy = async (text) => {
    try {
      await navigator.clipboard.writeText(text)
      message.success('已复制')
    } catch {
      message.error('复制失败，请手动选中复制')
    }
  }

  const handleMarkApplied = useCallback((row) => {
    Modal.confirm({
      title: '确认已应用到商品？',
      content: `确认后状态变为「已应用」，记录时间作为后续 ROI 对比的基线。
        原标题："${(row.original_title || '').slice(0, 50)}..."
        新标题："${(row.generated_title || '').slice(0, 50)}..."`,
      okText: '已改到商品，标记',
      onOk: async () => {
        try {
          const res = await applyGeneratedTitle(shopId, row.id)
          if (res.code === 0) {
            message.success('已标记「已应用」')
            fetchData()
          } else {
            message.error(res.msg || '操作失败')
          }
        } catch (e) {
          message.error(e?.response?.data?.msg || '网络错误')
        }
      },
    })
  }, [shopId, fetchData])

  const columns = useMemo(() => [
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 150,
      render: (v) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '商品',
      key: 'product',
      width: 200,
      render: (_, r) => (
        <Space size={8}>
          {r.image_url && (
            <img src={r.image_url} alt="" style={{ width: 32, height: 32, objectFit: 'cover', borderRadius: 2 }} />
          )}
          <div>
            <div style={{ fontSize: 13 }}>{r.product_name || <Text type="secondary">（无名）</Text>}</div>
            <Text type="secondary" style={{ fontSize: 11 }}>
              ID {r.product_id} · {r.platform?.toUpperCase()}
            </Text>
          </div>
        </Space>
      ),
    },
    {
      title: '原俄语标题',
      dataIndex: 'original_title',
      key: 'original_title',
      width: 260,
      ellipsis: true,
      render: (v) => v ? <Text style={{ fontSize: 12 }}>{v}</Text> : <Text type="secondary">（空）</Text>,
    },
    {
      title: 'AI 生成新标题',
      dataIndex: 'generated_title',
      key: 'generated_title',
      width: 320,
      render: (v) => (
        <Paragraph
          copyable={{ text: v }}
          style={{ margin: 0, fontSize: 12, color: '#3f8600' }}
          ellipsis={{ rows: 2, tooltip: v }}
        >
          {v}
        </Paragraph>
      ),
    },
    {
      title: '模型',
      dataIndex: 'ai_model',
      key: 'ai_model',
      width: 70,
      render: (v) => <Tag color="geekblue">{v?.toUpperCase() || '-'}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'approval_status',
      key: 'approval_status',
      width: 90,
      render: (s) => {
        const m = STATUS_META[s] || STATUS_META.pending
        return <Tag color={m.color}>{m.label}</Tag>
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 170,
      fixed: 'right',
      render: (_, r) => (
        <Space size={4}>
          <Button size="small" type="link" icon={<CopyOutlined />}
            onClick={() => handleCopy(r.generated_title)}>
            复制
          </Button>
          <Button size="small" type="link" onClick={() => setDetailRow(r)}>
            详情
          </Button>
          {r.approval_status !== 'applied' && (
            <Button size="small" type="link" icon={<CheckOutlined />}
              onClick={() => handleMarkApplied(r)}>
              标记已用
            </Button>
          )}
        </Space>
      ),
    },
  ], [handleMarkApplied])

  const pagination = useMemo(() => ({
    current: page,
    pageSize: size,
    total: data?.total || 0,
    showSizeChanger: true,
    pageSizeOptions: [10, 20, 50, 100],
    showTotal: (t) => `共 ${t} 条`,
  }), [page, size, data])

  const onPaginationChange = (p) => {
    if (p.current && p.current !== page) setPage(p.current)
    if (p.pageSize && p.pageSize !== size) {
      setSize(p.pageSize)
      setPage(1)
    }
  }

  const historyTabContent = (
    <>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="为什么要「标记已用」？"
        description="复制新标题 → 改到商品后，点「标记已用」。系统会记录改标题的时间点，在「改标题效果对比」Tab 里做前后 14 天 ROI 对比。"
      />

      <Space wrap size={[12, 12]} style={{ marginBottom: 16 }}>
        <Segmented
          value={approvalStatus}
          onChange={(v) => { setApprovalStatus(v); setPage(1) }}
          options={[
            { label: '全部', value: 'all' },
            { label: '待用', value: 'pending' },
            { label: '已应用', value: 'applied' },
            { label: '已拒', value: 'rejected' },
          ]}
        />
        <Input.Search
          placeholder="搜索原/新标题"
          value={keyword}
          onChange={e => setKeyword(e.target.value)}
          onSearch={() => { setPage(1); fetchData() }}
          allowClear
          style={{ width: 220 }}
        />
        <Button icon={<SyncOutlined />} onClick={fetchData}>重新加载</Button>
      </Space>

      <Table
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={data?.items || []}
        columns={columns}
        pagination={pagination}
        onChange={onPaginationChange}
        scroll={{ x: 1300 }}
      />
    </>
  )

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Title level={4} style={{ marginBottom: 4 }}>
          <LineChartOutlined /> SEO 效果报表
        </Title>
        <Text type="secondary">
          改标题前后效果对比 + AI 生成历史回溯。
          先在「AI 生成历史」里标记「已用」，系统会自动在「改标题效果对比」里追踪前后 14 天数据变化。
        </Text>
      </div>

      <Card>
        <Space style={{ marginBottom: 12 }}>
          <Text>店铺：</Text>
          <Select
            style={{ width: 240 }}
            placeholder="选择店铺"
            value={shopId}
            onChange={setShopId}
          >
            {shops.map(s => (
              <Option key={s.id} value={s.id}>
                [{PLATFORM_LABEL[s.platform] || s.platform}] {s.name}
              </Option>
            ))}
          </Select>
        </Space>

        <Tabs
          defaultActiveKey="roi"
          items={[
            {
              key: 'roi',
              label: <span><LineChartOutlined /> 改标题效果对比</span>,
              children: <RoiReportTab shopId={shopId} />,
            },
            {
              key: 'history',
              label: <span><HistoryOutlined /> AI 生成历史</span>,
              children: historyTabContent,
            },
          ]}
        />
      </Card>

      <Modal
        open={!!detailRow}
        onCancel={() => setDetailRow(null)}
        title="生成详情"
        width={880}
        footer={[
          <Button key="close" onClick={() => setDetailRow(null)}>关闭</Button>,
          detailRow && (
            <Button
              key="copy"
              type="primary"
              icon={<CopyOutlined />}
              onClick={() => handleCopy(detailRow.generated_title)}
            >
              复制新标题
            </Button>
          ),
        ]}
      >
        {detailRow && (() => {
          const stateText = detailRow.current_title === detailRow.generated_title
            ? { type: 'success', msg: '✓ 当前商品标题已和 AI 生成一致（疑似已应用）' }
            : detailRow.current_title === detailRow.original_title
              ? { type: 'warning', msg: '当前商品标题仍是原标题（尚未应用）' }
              : { type: 'info', msg: '当前商品标题已被手动或其他操作修改' }
          const colStyle = {
            padding: 10,
            borderRadius: 4,
            background: '#fafbff',
            border: '1px solid #e6edff',
            minHeight: 96,
            fontSize: 12,
            lineHeight: 1.6,
            wordBreak: 'break-word',
          }
          return (
            <>
              <div style={{ marginBottom: 8 }}>
                <Text strong>{detailRow.product_name || `ID ${detailRow.product_id}`}</Text>
                <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                  ID {detailRow.product_id}
                </Text>
              </div>

              <Row gutter={8} style={{ marginBottom: 12 }}>
                <Col span={8}>
                  <div style={{ fontSize: 11, color: '#999', marginBottom: 4 }}>原俄语标题</div>
                  <div style={colStyle}>
                    {detailRow.original_title
                      ? <Text copyable={{ text: detailRow.original_title }}>{detailRow.original_title}</Text>
                      : <Text type="secondary">（空）</Text>}
                  </div>
                </Col>
                <Col span={8}>
                  <div style={{ fontSize: 11, color: '#3f8600', marginBottom: 4 }}>AI 生成新标题</div>
                  <div style={{ ...colStyle, background: '#f6ffed', border: '1px solid #b7eb8f' }}>
                    <Text copyable={{ text: detailRow.generated_title }} strong style={{ color: '#3f8600' }}>
                      {detailRow.generated_title}
                    </Text>
                  </div>
                </Col>
                <Col span={8}>
                  <div style={{ fontSize: 11, color: '#999', marginBottom: 4 }}>当前商品实际标题</div>
                  <div style={colStyle}>
                    {detailRow.current_title
                      ? <Text>{detailRow.current_title}</Text>
                      : <Text type="secondary">（空）</Text>}
                  </div>
                </Col>
              </Row>

              <Alert
                type={stateText.type}
                showIcon
                message={stateText.msg}
                style={{ marginBottom: 12, padding: '6px 12px' }}
              />

              <Descriptions column={1} size="small">
                <Descriptions.Item label="AI 决策说明">
                  {detailRow.reasoning || <Text type="secondary">（无）</Text>}
                </Descriptions.Item>
                <Descriptions.Item label="用到的关键词">
                  <Space size={4} wrap>
                    {(detailRow.keywords_used || []).map((k, i) => (
                      <Tag key={i} color="blue" style={{ margin: 0 }}>{k}</Tag>
                    ))}
                  </Space>
                </Descriptions.Item>
                <Descriptions.Item label="模型 / 时间">
                  <Tag color="geekblue">{detailRow.ai_model?.toUpperCase()}</Tag>
                  {' · '}
                  {detailRow.created_at && new Date(detailRow.created_at).toLocaleString('zh-CN')}
                  {detailRow.applied_at && (
                    <>
                      {' · 应用于 '}
                      {new Date(detailRow.applied_at).toLocaleString('zh-CN')}
                    </>
                  )}
                </Descriptions.Item>
              </Descriptions>
            </>
          )
        })()}
      </Modal>
    </div>
  )
}

export default Report
