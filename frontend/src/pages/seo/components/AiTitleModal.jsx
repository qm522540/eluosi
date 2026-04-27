import { useState, useEffect, useMemo } from 'react'
import {
  Modal, Button, Typography, Space, Tag, Alert, Descriptions, Spin, message,
  Checkbox, Tooltip,
} from 'antd'
import {
  CopyOutlined, ThunderboltOutlined, RobotOutlined, CheckCircleOutlined,
} from '@ant-design/icons'
import { generateSeoTitle, applyGeneratedTitle, previewSeoTitleInputs } from '@/api/seo'
import { copyText } from '@/utils/clipboard'

const { Text, Paragraph } = Typography

/**
 * AI 标题生成 Modal
 *
 * 交互：
 * 1. 打开时展示"即将融合"的候选词清单 + 当前商品原标题 (尚未调 AI)
 * 2. 用户点 [生成] → loading → 展示结果（新标题 + AI 说明 + 实际用了哪些词）
 * 3. 一键复制新标题到剪贴板（提示用户去商品列表粘贴）
 *
 * Props:
 *   open, onClose
 *   shopId
 *   productId
 *   productName        当前商品名（中文）
 *   currentTitle       当前俄语标题（用户看到"改成什么"的对照）
 *   selectedCandidates [{id, keyword, ...}, ...]   用户勾选的候选词（只来自同一商品）
 */
const AiTitleModal = ({
  open, onClose,
  shopId, productId, productName, currentTitle,
  selectedCandidates,
}) => {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)

  // preview 数据 (反哺词带翻译 + 跨店本类目 Top 5)
  const [preview, setPreview] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)

  // 用户勾选 (默认全选)
  const [selectedCandidateIds, setSelectedCandidateIds] = useState(new Set())
  const [selectedCategoryKeywords, setSelectedCategoryKeywords] = useState(new Set())

  // 每次重新打开清空上一次结果
  useEffect(() => {
    if (open) setResult(null)
  }, [open, productId])

  // 打开时拉 preview
  useEffect(() => {
    if (!open || !shopId || !productId) return
    const ids = (selectedCandidates || []).map(c => c.id)
    setPreviewLoading(true)
    previewSeoTitleInputs(shopId, productId, ids)
      .then(r => {
        if (r?.data) {
          setPreview(r.data)
          // 默认全选
          setSelectedCandidateIds(new Set((r.data.candidates || []).map(c => c.id)))
          setSelectedCategoryKeywords(new Set((r.data.category_top_keywords || []).map(k => k.keyword)))
        }
      })
      .catch(e => message.error(e?.response?.data?.msg || '加载预览数据失败'))
      .finally(() => setPreviewLoading(false))
  }, [open, shopId, productId, selectedCandidates])

  const toggleSet = (set, setter) => (val) => {
    const next = new Set(set)
    if (next.has(val)) next.delete(val); else next.add(val)
    setter(next)
  }

  const handleGenerate = async () => {
    if (!shopId || !productId) return
    if (selectedCandidateIds.size === 0 && selectedCategoryKeywords.size === 0) {
      message.warning('至少选一个反哺词或跨店类目热门词')
      return
    }
    setLoading(true)
    try {
      const ids = Array.from(selectedCandidateIds)
      const extraKws = Array.from(selectedCategoryKeywords)
      const res = await generateSeoTitle(shopId, productId, ids, extraKws)
      if (res.code === 0) {
        setResult(res.data)
      } else {
        message.error(res.msg || '生成失败')
      }
    } catch (e) {
      message.error(e?.response?.data?.msg || e?.message || '网络错误')
    } finally {
      setLoading(false)
    }
  }

  const handleCopy = async () => {
    if (!result?.new_title) return
    const ok = await copyText(result.new_title)
    if (ok) {
      message.success('已复制到剪贴板，去商品列表「编辑商品」粘贴到标题即可')
    } else {
      message.error('复制失败，请手动选中文字复制')
    }
  }

  const handleApply = () => {
    if (!result?.generated_content_id) return
    Modal.confirm({
      title: '确认启用新标题？',
      width: 560,
      icon: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
      content: (
        <div style={{ fontSize: 13, lineHeight: 1.7 }}>
          <div style={{ marginBottom: 8 }}>
            <Text type="secondary">原标题：</Text>
            <div style={{ background: '#fafafa', padding: '4px 8px', borderRadius: 4, marginTop: 2 }}>
              {currentTitle || <Text type="secondary">（空）</Text>}
            </div>
          </div>
          <div style={{ marginBottom: 12 }}>
            <Text type="secondary">新标题：</Text>
            <div style={{ background: '#f6ffed', padding: '4px 8px', borderRadius: 4, marginTop: 2, color: '#222', fontWeight: 500 }}>
              {result.new_title}
            </div>
          </div>
          <div style={{ background: '#fffbe6', padding: '8px 10px', borderRadius: 4, border: '1px solid #ffe58f' }}>
            <div style={{ marginBottom: 4 }}><strong>启用后系统会做：</strong></div>
            <div style={{ paddingLeft: 12 }}>
              ✓ 标记此标题为「已应用」<br/>
              ✓ 以本时间点为基线追踪 ROI（改前 / 改后曝光、订单、ROAS 对比）
            </div>
            <div style={{ marginTop: 8, color: '#d46b08' }}>
              ⚠ 本期暂不自动写回到 WB / Ozon 商品后台，请你<strong>手动</strong>到平台后台「编辑商品」粘贴新标题让平台真正生效
            </div>
          </div>
        </div>
      ),
      okText: '确认启用',
      cancelText: '取消',
      // antd: onOk 返 Promise 时按钮自动处理 confirmLoading（无需手动 state）
      onOk: async () => {
        try {
          const r = await applyGeneratedTitle(shopId, result.generated_content_id)
          if (r?.code === 0) {
            message.success('已启用，ROI 基线已建立。请到平台后台粘贴新标题让平台生效。')
            onClose && onClose()
          } else {
            message.warning(`启用失败：${r?.msg || '未知错误'}`)
            return Promise.reject()  // 返 reject 让 confirm 不关闭，用户可以重试
          }
        } catch (e) {
          message.error(e?.response?.data?.msg || e?.message || '启用失败')
          return Promise.reject()
        }
      },
    })
  }

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={<Space><RobotOutlined /><span>AI 融合关键词生成新标题</span></Space>}
      width={1100}
      destroyOnClose
      footer={result ? [
        <Button key="close" onClick={onClose}>关闭</Button>,
        <Button key="regen" icon={<ThunderboltOutlined />} onClick={handleGenerate} loading={loading}>
          重新生成
        </Button>,
        <Button key="copy" icon={<CopyOutlined />} onClick={handleCopy}>
          一键复制新标题
        </Button>,
        <Button
          key="apply"
          type="primary"
          icon={<CheckCircleOutlined />}
          onClick={handleApply}
        >
          启用新标题
        </Button>,
      ] : [
        <Button key="cancel" onClick={onClose}>取消</Button>,
        <Button
          key="gen"
          type="primary"
          icon={<ThunderboltOutlined />}
          onClick={handleGenerate}
          loading={loading}
          disabled={previewLoading || (selectedCandidateIds.size === 0 && selectedCategoryKeywords.size === 0)}
        >
          开始生成（约 5-15 秒）
        </Button>,
      ]}
    >
      <Descriptions size="small" column={1} bordered style={{ marginBottom: 12 }}>
        <Descriptions.Item label="商品">{productName || `ID ${productId}`}</Descriptions.Item>
        <Descriptions.Item label="当前俄语标题">
          {currentTitle
            ? (
              <Space size={6}>
                <Text>{currentTitle}</Text>
                <CopyOutlined
                  style={{ cursor: 'pointer', color: '#1677ff' }}
                  onClick={async () => {
                    const ok = await copyText(currentTitle)
                    if (ok) message.success('已复制当前标题')
                    else message.error('复制失败，请手动选中复制')
                  }}
                />
              </Space>
            )
            : <Text type="secondary">（空 / 未同步）</Text>}
        </Descriptions.Item>
      </Descriptions>

      {previewLoading ? (
        <div style={{ textAlign: 'center', padding: 24 }}>
          <Spin tip="加载预览数据..." />
        </div>
      ) : preview ? (
        <>
          {/* 选中反哺词 (带翻译, 复选框默认全选) */}
          {(preview.candidates || []).length > 0 && (
            <div style={{ marginBottom: 12, padding: '10px 12px', border: '1px solid #e8e8e8', borderRadius: 4 }}>
              <Space style={{ marginBottom: 6 }}>
                <Text strong style={{ fontSize: 12 }}>
                  💡 选中反哺词 ({selectedCandidateIds.size} / {preview.candidates.length})
                </Text>
                <Text type="secondary" style={{ fontSize: 11 }}>用户在表格里勾选的本商品候选词</Text>
                <Button size="small" type="link" style={{ fontSize: 11, padding: 0 }}
                  onClick={() => {
                    if (selectedCandidateIds.size === preview.candidates.length) setSelectedCandidateIds(new Set())
                    else setSelectedCandidateIds(new Set(preview.candidates.map(c => c.id)))
                  }}>
                  {selectedCandidateIds.size === preview.candidates.length ? '全不选' : '全选'}
                </Button>
              </Space>
              <Space size={[6, 6]} wrap>
                {preview.candidates.map(c => {
                  const orders = (c.organic_orders || 0) + (c.paid_orders || 0)
                  return (
                    <Checkbox
                      key={'cand-' + c.id}
                      checked={selectedCandidateIds.has(c.id)}
                      onChange={toggleSet(selectedCandidateIds, setSelectedCandidateIds).bind(null, c.id)}
                    >
                      <Tooltip title={`score ${c.score?.toFixed?.(1) || '-'} / 自然曝光 ${c.organic_impressions} / 订单 ${orders}`}>
                        <span style={{ fontSize: 11, display: 'inline-block', lineHeight: 1.3 }}>
                          <div>
                            {c.keyword}
                            <Text type="secondary" style={{ fontSize: 10, marginLeft: 4 }}>
                              ({c.organic_impressions}曝/{orders}单)
                            </Text>
                          </div>
                          {c.keyword_zh && c.keyword_zh !== c.keyword && (
                            <div style={{ fontSize: 10, color: '#1677ff' }}>{c.keyword_zh}</div>
                          )}
                        </span>
                      </Tooltip>
                    </Checkbox>
                  )
                })}
              </Space>
            </div>
          )}

          {/* 跨店本类目热门词 Top 5 */}
          {(preview.category_top_keywords || []).length > 0 && (
            <div style={{ marginBottom: 12, padding: '10px 12px', background: '#fafffa', border: '1px solid #b7eb8f', borderRadius: 4 }}>
              <Space style={{ marginBottom: 6 }}>
                <Text strong style={{ fontSize: 12 }}>
                  🔥 跨店本类目热门关键词 ({selectedCategoryKeywords.size} / {preview.category_top_keywords.length})
                </Text>
                <Text type="secondary" style={{ fontSize: 11 }}>同子类目跨店聚合, 按订单+曝光降序 Top 5</Text>
                <Button size="small" type="link" style={{ fontSize: 11, padding: 0 }}
                  onClick={() => {
                    const all = preview.category_top_keywords.map(k => k.keyword)
                    if (all.every(k => selectedCategoryKeywords.has(k))) setSelectedCategoryKeywords(new Set())
                    else setSelectedCategoryKeywords(new Set(all))
                  }}>
                  {preview.category_top_keywords.every(k => selectedCategoryKeywords.has(k.keyword)) ? '全不选' : '全选'}
                </Button>
              </Space>
              <Space size={[6, 6]} wrap>
                {preview.category_top_keywords.map(k => (
                  <Checkbox
                    key={'cat-' + k.keyword}
                    checked={selectedCategoryKeywords.has(k.keyword)}
                    onChange={toggleSet(selectedCategoryKeywords, setSelectedCategoryKeywords).bind(null, k.keyword)}
                  >
                    <Tooltip title={`总订单 ${k.total_orders} / 总曝光 ${k.total_impressions} / 覆盖 ${k.product_count} 商品`}>
                      <span style={{ fontSize: 11, display: 'inline-block', lineHeight: 1.3 }}>
                        <div>
                          {k.keyword}
                          <Text type="secondary" style={{ fontSize: 10, marginLeft: 4 }}>
                            ({k.total_orders}单/{k.total_impressions}曝)
                          </Text>
                        </div>
                        {k.keyword_zh && k.keyword_zh !== k.keyword && (
                          <div style={{ fontSize: 10, color: '#1677ff' }}>{k.keyword_zh}</div>
                        )}
                      </span>
                    </Tooltip>
                  </Checkbox>
                ))}
              </Space>
            </div>
          )}
        </>
      ) : null}

      {loading && (
        <div style={{ textAlign: 'center', padding: '40px 0' }}>
          <Spin size="large" />
          <div style={{ marginTop: 12, color: '#999' }}>AI 正在融合关键词（走 GLM 俄语模型）…</div>
        </div>
      )}

      {!loading && result && (
        <>
          <Alert
            type="success"
            showIcon
            style={{ marginBottom: 12 }}
            message={(
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                <Paragraph style={{ fontSize: 15, marginBottom: 0, lineHeight: 1.6, fontWeight: 500, flex: 1 }}>
                  {result.new_title}
                </Paragraph>
                <CopyOutlined
                  style={{ cursor: 'pointer', color: '#1677ff', marginTop: 4 }}
                  onClick={handleCopy}
                />
              </div>
            )}
            description={result.reasoning ? (
              <Text type="secondary" style={{ fontSize: 12 }}>{result.reasoning}</Text>
            ) : null}
          />

          <div style={{
            padding: '8px 12px',
            background: '#fafbff',
            border: '1px solid #e6edff',
            borderRadius: 4,
            marginBottom: 12,
            fontSize: 12,
            color: '#666',
          }}>
            <Space size={12} wrap>
              <span><Text type="secondary">模型</Text> {result.ai_model?.toUpperCase()}</span>
              <span><Text type="secondary">耗时</Text> {result.duration_ms} ms</span>
              <span><Text type="secondary">Token</Text> {result.tokens?.total}</span>
              <span><Text type="secondary">用词</Text> {result.included_keywords?.length || 0} 个</span>
            </Space>
            {result.included_keywords?.length > 0 && (
              <div style={{ marginTop: 6 }}>
                <Space size={4} wrap>
                  {result.included_keywords.map((kw, i) => (
                    <Tag key={i} color="blue" style={{ margin: 0 }}>{kw}</Tag>
                  ))}
                </Space>
              </div>
            )}
          </div>

          {result.preserved_keywords?.length > 0 && (
            <Alert
              type={result.dropped_preserve?.length ? 'warning' : 'info'}
              showIcon
              style={{ marginBottom: 12 }}
              message={(
                <span>
                  已识别 <strong>{result.preserved_keywords.length}</strong> 个原标题里的高价值词（有订单或曝光 ≥ 20），AI 已被要求保留：
                </span>
              )}
              description={(
                <div>
                  <Space size={4} wrap style={{ marginBottom: result.dropped_preserve?.length ? 6 : 0 }}>
                    {result.preserved_keywords.map((kw, i) => {
                      const dropped = result.dropped_preserve?.includes(kw)
                      return (
                        <Tag key={i} color={dropped ? 'red' : 'green'} style={{ margin: 0 }}>
                          {dropped ? '✗ ' : '✓ '}{kw}
                        </Tag>
                      )
                    })}
                  </Space>
                  {result.dropped_preserve?.length > 0 && (
                    <Text type="danger" style={{ fontSize: 12 }}>
                      ⚠️ AI 未保留红色标签的词，采用前请留意 —— 建议点「重新生成」再试，或手动补回。
                    </Text>
                  )}
                </div>
              )}
            />
          )}

          <Text type="secondary" style={{ fontSize: 12 }}>
            一期仅生成建议，请复制新标题到「商品管理 → 编辑商品」手动粘贴。
          </Text>
        </>
      )}

      {!loading && !result && !selectedCandidates?.length && (
        <Alert
          type="warning"
          showIcon
          message="尚未选中任何候选词"
          description="请先在候选词表格里勾选同一商品的若干词（建议 3-8 个），再点「AI 生成标题」。"
        />
      )}
    </Modal>
  )
}

export default AiTitleModal
