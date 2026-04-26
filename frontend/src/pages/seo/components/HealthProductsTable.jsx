import { useState, useCallback } from 'react'
import { Table, Tag, Space, Typography, Tooltip, Progress, Button, message, Modal, Input } from 'antd'
import { RobotOutlined, ThunderboltOutlined, EditOutlined } from '@ant-design/icons'
import { getProductMissingCandidates } from '@/api/seo'
import { translateKeywords, updateTranslation } from '@/api/keyword_stats'
import AiTitleModal from './AiTitleModal'
import AiDescriptionModal from './AiDescriptionModal'

const { Text } = Typography

// 与后端 keyword_stats._classify_word_type 一致：按空格分词
const classifyWordType = (kw) => {
  const n = (kw || '').trim().split(/\s+/).filter(Boolean).length
  if (n <= 1) return 'single'
  if (n <= 4) return 'short'
  return 'long'
}
const WORD_TYPE_MAP = {
  single: { label: '单词', color: 'default' },
  short:  { label: '短词', color: 'blue' },
  long:   { label: '长尾', color: 'purple' },
}

const SOURCE_TAG = {
  paid: {
    color: 'purple',
    label: '本店付费投放',
    short: '付费',
    tip: '你在本店给这个商品配过该关键词的广告，且实际有曝光/订单数据。这是"花钱买过验证"的词。',
  },
  organic: {
    color: 'blue',
    label: '本店自然搜索',
    short: '自然',
    tip: '用户在 OZON/WB 搜索框输入该词后看到了本商品（来自 search-texts / GetProductQueries）。这是"用户主动找你"的词，加进标题最有价值。',
  },
  cross_shop: {
    color: 'orange',
    label: '他店自然搜索',
    short: '跨店',
    tip: '同 SKU 商品在你旗下其他店里被用户搜过该词（也是搜索流量，非广告投放）。本店是新店没数据时尤其有参考价值。',
  },
  unknown: {
    color: 'default',
    label: '其他',
    short: '其他',
    tip: '来源不明确',
  },
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
  // 行展开状态：每个 pid 独立维护数据/loading/已勾选
  const [expandedKeys, setExpandedKeys] = useState([])
  const [expandedData, setExpandedData] = useState({})    // pid -> items[]
  const [expandedLoading, setExpandedLoading] = useState({}) // pid -> bool
  const [selectedByPid, setSelectedByPid] = useState({})  // pid -> selected rows
  // "AI 优化标题"按钮 per-row loading（fetch 候选词时显示）
  const [titleLoading, setTitleLoading] = useState({})    // pid -> bool
  // 翻译缓存（俄→中），全局 dict 跨 pid 共享，命中 L2 ru_zh_dict 瞬间返
  const [kwTranslations, setKwTranslations] = useState({})

  // AiTitleModal 控制
  const [aiModal, setAiModal] = useState({
    open: false, productId: null, productName: '', currentTitle: '', selected: [],
  })
  // AiDescriptionModal 控制（描述不需要 selected 候选词，后端自取全集）
  const [descModal, setDescModal] = useState({
    open: false, productId: null, productName: '', currentTitle: '', currentDescription: '',
  })

  // "AI 优化标题"按钮：自动取该商品候选词 Top 3 → 当前页弹 AiTitleModal
  // 旧版是 navigate('/seo/optimize?...') 跳转优化页，改 in-page 保持上下文
  const handleAiTitle = async (record) => {
    const pid = record.product_id
    let items = expandedData[pid]
    if (!items) {
      setTitleLoading(prev => ({ ...prev, [pid]: true }))
      try {
        const r = await getProductMissingCandidates(shopId, pid)
        items = r?.data?.items || []
        setExpandedData(prev => ({ ...prev, [pid]: items }))
      } catch (e) {
        message.error(e?.response?.data?.msg || e?.message || '拉取候选词失败')
        return
      } finally {
        setTitleLoading(prev => ({ ...prev, [pid]: false }))
      }
    }
    const top3 = items.slice(0, 3)  // 后端按 score desc 已排
    if (!top3.length) {
      message.warning('该商品暂无可用候选词')
      return
    }
    setAiModal({
      open: true,
      productId: pid,
      productName: record.product_name,
      currentTitle: record.current_title || '',
      selected: top3.map(it => ({ id: it.candidate_id, keyword: it.keyword })),
    })
  }

  // "AI 优化描述"按钮：直接打开描述 Modal（候选词由后端自取，不需要前端预拉）
  const handleAiDescription = (record) => {
    setDescModal({
      open: true,
      productId: record.product_id,
      productName: record.product_name,
      currentTitle: record.current_title || '',
      currentDescription: record.current_description || '',
    })
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
        const items = res.data.items || []
        setExpandedData(prev => ({ ...prev, [pid]: items }))
        // 异步批量翻译缺词（命中 L2 ru_zh_dict 缓存瞬返；新词走 Kimi 后写回 DB）
        const kws = items.map(it => it.keyword).filter(Boolean)
        if (kws.length > 0) {
          translateKeywords(kws).then(r => {
            if (r.code === 0) {
              setKwTranslations(prev => ({ ...prev, ...(r.data || {}) }))
            }
          }).catch(() => {})
        }
      } else {
        message.error(res.msg || '拉取失败')
      }
    } catch {
      message.error('拉取失败')
    } finally {
      setExpandedLoading(prev => ({ ...prev, [pid]: false }))
    }
  }, [shopId, expandedData])

  const handleEditTranslation = (v) => {
    const zh = kwTranslations[v] || ''
    Modal.confirm({
      title: '编辑中文翻译',
      icon: null,
      content: (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 12, color: '#999', marginBottom: 6 }}>俄文：{v}</div>
          <Input id={`health-tr-input-${v}`} defaultValue={zh} placeholder="输入中文翻译" />
          <div style={{ fontSize: 11, color: '#bbb', marginTop: 6 }}>
            手动修改后标记为 manual，之后 AI 不会覆盖此翻译
          </div>
        </div>
      ),
      onOk: async () => {
        const newVal = document.getElementById(`health-tr-input-${v}`)?.value?.trim()
        if (!newVal) return
        try {
          await updateTranslation(v, newVal)
          setKwTranslations(prev => ({ ...prev, [v]: newVal }))
          message.success('翻译已更新')
        } catch (e) {
          message.error(e?.response?.data?.msg || '更新失败')
        }
      },
    })
  }

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
      title: (
        <Tooltip title="付费投放=你给该商品配过该词的广告并产生曝光；自然搜索=用户主动搜该词找到商品；他店自然=同款 SKU 在你其他店有自然搜索数据。">
          <span style={{ cursor: 'help' }}>来源 ⓘ</span>
        </Tooltip>
      ),
      key: 'source', width: 130,
      render: (_, r) => {
        const meta = SOURCE_TAG[r.source_type] || SOURCE_TAG.unknown
        return (
          <Tooltip title={meta.tip}>
            <Tag color={meta.color} style={{ margin: 0, cursor: 'help' }}>{meta.label}</Tag>
          </Tooltip>
        )
      },
    },
    {
      title: '关键词', dataIndex: 'keyword', key: 'keyword',
      render: (v) => {
        const zh = kwTranslations[v]
        const hasZh = zh && zh !== v
        const wt = WORD_TYPE_MAP[classifyWordType(v)]
        return (
          <Space direction="vertical" size={1} style={{ lineHeight: 1.2 }}>
            <Space size={4} style={{ alignItems: 'center' }}>
              <Text style={{ fontSize: 12, fontWeight: 500 }}>{v}</Text>
              {wt && (
                <Tag color={wt.color} style={{ margin: 0, fontSize: 10, padding: '0 4px', lineHeight: '14px' }}>
                  {wt.label}
                </Tag>
              )}
            </Space>
            <Space size={4} style={{ alignItems: 'center' }}>
              <Text style={{ fontSize: 11, color: hasZh ? '#999' : '#ccc' }}>
                {hasZh ? zh : '翻译中...'}
              </Text>
              <EditOutlined
                style={{ fontSize: 10, color: '#bbb', cursor: 'pointer' }}
                onClick={() => handleEditTranslation(v)}
              />
            </Space>
          </Space>
        )
      },
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
      title: <Tooltip title="用户搜该词后看到商品并加进购物车的次数">加购</Tooltip>,
      key: 'atc', width: 70, align: 'right',
      render: (_, r) => {
        const v = r.cross_add_to_cart ?? r.organic_add_to_cart
        return v != null && v > 0 ? <Text style={{ fontSize: 12, color: '#fa8c16' }}>{v}</Text> : <Text type="secondary">-</Text>
      },
    },
    {
      title: '订单', key: 'orders', width: 70, align: 'right',
      render: (_, r) => {
        const v = r.cross_orders ?? r.paid_orders ?? r.organic_orders
        return v != null ? <Text style={{ fontSize: 12, color: v > 0 ? '#3f8600' : undefined }}>{v}</Text> : <Text type="secondary">-</Text>
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
              <span>{record.product_name}</span>
              <span style={{ color: '#1677ff', fontWeight: 600, marginLeft: 8 }}>{record.sku || '（无编码）'}</span>
              <span style={{ color: '#666', fontWeight: 400, marginLeft: 8 }}>· 全部缺词 {items.length} 个</span>
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
              <div style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 13, fontWeight: 500, color: '#222' }}>
                {r.product_name || <Text type="secondary">（无名）</Text>}
              </div>
            </Tooltip>
            <div style={{ fontSize: 11, fontWeight: 600, color: '#1677ff' }}>
              {r.sku || <Text type="secondary">（无编码）</Text>}
            </div>
            <Text type="secondary" style={{ fontSize: 11 }}>{r.platform?.toUpperCase()}</Text>
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
          <DimensionBar label="描述长度" detail={r.dimensions.description_length} />
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
        return (
          <Space size={4} direction="vertical" style={{ width: '100%' }}>
            {r.missing_top_keywords.map((k, i) => {
              const stype = k.source_type || 'unknown'
              const meta = SOURCE_TAG[stype] || SOURCE_TAG.unknown
              return (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  <Tooltip title={meta.tip}>
                    <Tag color={meta.color} style={{ margin: 0, fontSize: 10, padding: '0 4px', lineHeight: '16px', cursor: 'help' }}>
                      {meta.short}
                    </Tag>
                  </Tooltip>
                  <Tag color={meta.color} style={{ margin: 0 }}>{k.keyword}</Tag>
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
            loading={titleLoading[r.product_id]}
            onClick={() => handleAiTitle(r)}
            disabled={!r.candidate_count}
          >
            AI 优化标题
          </Button>
          <Button
            type="primary"
            size="small"
            icon={<RobotOutlined />}
            onClick={() => handleAiDescription(r)}
            disabled={!r.candidate_count}
          >
            AI 优化描述
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
      <AiDescriptionModal
        open={descModal.open}
        onClose={() => setDescModal(prev => ({ ...prev, open: false }))}
        shopId={shopId}
        productId={descModal.productId}
        productName={descModal.productName}
        currentTitle={descModal.currentTitle}
        currentDescription={descModal.currentDescription}
      />
    </>
  )
}

export default HealthProductsTable
