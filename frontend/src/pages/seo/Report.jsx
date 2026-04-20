import { useState, useEffect, useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Typography, Card, Space, Select, Segmented, Input, Button, Table, Tag,
  message, Modal, Descriptions, Alert,
} from 'antd'
import {
  CopyOutlined, CheckOutlined, RobotOutlined, SyncOutlined,
} from '@ant-design/icons'
import { getShops } from '@/api/shops'
import { getGeneratedTitles, applyGeneratedTitle } from '@/api/seo'

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

  const handleMarkApplied = async (row) => {
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
  }

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
  ], [shopId])

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

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Title level={4} style={{ marginBottom: 4 }}>
          <RobotOutlined /> AI 生成标题历史
        </Title>
        <Text type="secondary">
          每次在 SEO 优化建议页点「AI 生成标题」的结果都会记录在这里。
          即使当时没复制，之后也能回溯、重新复制、标记为已应用。
        </Text>
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="为什么要「标记已用」？"
        description="复制新标题 → 改到商品后，点「标记已用」。系统会记录改标题的时间点，为二期「改标题前后 14 天 ROI 对比」功能做基线。"
      />

      <Card>
        <Space wrap size={[12, 12]} style={{ marginBottom: 16 }}>
          <Select
            style={{ width: 220 }}
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
      </Card>

      <Modal
        open={!!detailRow}
        onCancel={() => setDetailRow(null)}
        title="生成详情"
        width={720}
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
        {detailRow && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="商品">
              {detailRow.product_name || `ID ${detailRow.product_id}`}
            </Descriptions.Item>
            <Descriptions.Item label="原俄语标题">
              <Text copyable>{detailRow.original_title || '（空）'}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="AI 生成新标题">
              <Text copyable strong style={{ color: '#3f8600' }}>
                {detailRow.generated_title}
              </Text>
            </Descriptions.Item>
            <Descriptions.Item label="当前商品实际标题">
              <Text type="secondary">
                {detailRow.current_title || '（空）'}
              </Text>
              <br/>
              <Text type="secondary" style={{ fontSize: 11 }}>
                {detailRow.current_title === detailRow.generated_title
                  ? '✓ 已和新标题一致（疑似已应用）'
                  : detailRow.current_title === detailRow.original_title
                    ? '与生成时原标题一致（尚未应用）'
                    : '已被手动/其他操作修改'}
              </Text>
            </Descriptions.Item>
            <Descriptions.Item label="AI 决策说明">
              {detailRow.reasoning || <Text type="secondary">（无）</Text>}
            </Descriptions.Item>
            <Descriptions.Item label="用到的关键词">
              <Space size={4} wrap>
                {(detailRow.keywords_used || []).map((k, i) => (
                  <Tag key={i} color="green">{k}</Tag>
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
        )}
      </Modal>
    </div>
  )
}

export default Report
