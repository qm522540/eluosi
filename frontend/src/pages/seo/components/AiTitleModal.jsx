import { useState, useEffect } from 'react'
import {
  Modal, Button, Typography, Space, Tag, Alert, Descriptions, Spin, message,
  Checkbox, Tooltip, Input,
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
  // 当前俄语标题是否喂给 AI (默认 true)
  const [includeCurrentTitle, setIncludeCurrentTitle] = useState(true)
  // 用户手动输入关键词 3 个
  const [manualKeywords, setManualKeywords] = useState(['', '', ''])

  // 每次重新打开清空上一次结果
  useEffect(() => {
    if (open) setResult(null)
  }, [open, productId])

  // 打开时拉 preview + 重置可编辑状态
  useEffect(() => {
    if (!open || !shopId || !productId) return
    const ids = (selectedCandidates || []).map(c => c.id)
    setPreviewLoading(true)
    setIncludeCurrentTitle(true)
    setManualKeywords(['', '', ''])
    previewSeoTitleInputs(shopId, productId, ids)
      .then(r => {
        if (r?.data) {
          setPreview(r.data)
          // 反哺词默认全选
          const candKws = new Set((r.data.candidates || []).map(c => c.keyword))
          setSelectedCandidateIds(new Set((r.data.candidates || []).map(c => c.id)))
          // 跨店类目词默认勾选规则:
          //  - 跟反哺词重复 → 不勾(避免给 AI 同词喂两次)
          //  - 看起来跨品类 (looks_cross_category=true) → 不勾(让用户决定)
          //  - 其余默认勾上
          setSelectedCategoryKeywords(new Set(
            (r.data.category_top_keywords || [])
              .filter(k => !candKws.has(k.keyword) && !k.looks_cross_category)
              .map(k => k.keyword),
          ))
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
    const cleanedManual = manualKeywords.map(k => k.trim()).filter(Boolean)
    if (selectedCandidateIds.size === 0 && selectedCategoryKeywords.size === 0 && cleanedManual.length === 0) {
      message.warning('至少选一个反哺词 / 跨店类目词 / 或填一个手动输入词')
      return
    }
    setLoading(true)
    try {
      const ids = Array.from(selectedCandidateIds)
      const extraKws = Array.from(selectedCategoryKeywords)
      const res = await generateSeoTitle(shopId, productId, ids, extraKws, {
        includeCurrentTitle,
        manualKeywords: cleanedManual,
      })
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
      title: '确认启用新标题?',
      width: 600,
      icon: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
      content: (
        <div style={{ fontSize: 13, lineHeight: 1.7 }}>
          <div style={{ marginBottom: 8 }}>
            <Text type="secondary">原标题:</Text>
            <div style={{ background: '#fafafa', padding: '4px 8px', borderRadius: 4, marginTop: 2 }}>
              {currentTitle || <Text type="secondary">(空)</Text>}
            </div>
          </div>
          <div style={{ marginBottom: 12 }}>
            <Text type="secondary">新标题:</Text>
            <div style={{ background: '#f6ffed', padding: '4px 8px', borderRadius: 4, marginTop: 2, color: '#222', fontWeight: 500 }}>
              {result.new_title}
            </div>
          </div>
          <div style={{ background: '#fffbe6', padding: '8px 10px', borderRadius: 4, border: '1px solid #ffe58f' }}>
            <div style={{ marginBottom: 4 }}><strong>启用后系统会做:</strong></div>
            <div style={{ paddingLeft: 12 }}>
              ✓ 改本地数据库标题为新标题 (健康诊断等页面立即同步)<br/>
              ✓ 调用 <strong>Ozon API</strong> 把平台后台商品名也改成新标题 (1-5 分钟生效)<br/>
              ✓ 标记此标题为「已应用」, 以本时间点为基线追踪 ROI 对比
            </div>
            <div style={{ marginTop: 8, color: '#d46b08' }}>
              ⚠ <strong>WB 平台</strong>暂不支持 API 写回, 请手动到 WB 后台粘贴新标题
            </div>
          </div>
        </div>
      ),
      okText: '确认启用',
      cancelText: '取消',
      onOk: async () => {
        try {
          const r = await applyGeneratedTitle(shopId, result.generated_content_id)
          if (r?.code === 0) {
            const wb = r.data?.platform_writeback
            if (wb?.status === 'submitted') {
              message.success(`已启用并提交 Ozon 写回 (task_id=${wb.task_id}), 1-5 分钟生效`, 6)
            } else if (wb?.status === 'failed') {
              message.warning(`本地标题已改, 但 Ozon API 写回失败: ${wb.msg} — 请手动到 Ozon 后台改`, 8)
            } else {
              message.success(`已启用 (本地已改). ${wb?.msg || ''}`, 5)
            }
            onClose && onClose()
          } else {
            message.warning(`启用失败: ${r?.msg || '未知错误'}`)
            return Promise.reject()
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
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="勾选哪些数据喂给 AI ─ 默认全选, 去掉勾就不传给 AI。AI 会基于「当前俄语标题」做融合改写。"
      />

      <Descriptions size="small" column={1} bordered style={{ marginBottom: 12 }}>
        <Descriptions.Item
          label={(
            <Space size={6}>
              <Checkbox
                checked={includeCurrentTitle}
                onChange={(e) => setIncludeCurrentTitle(e.target.checked)}
              />
              <span>当前俄语标题</span>
            </Space>
          )}
        >
          {currentTitle
            ? (
              <Space size={6}>
                <Text style={{ color: includeCurrentTitle ? '#222' : '#bbb' }}>{currentTitle}</Text>
                <CopyOutlined
                  style={{ cursor: 'pointer', color: '#1677ff' }}
                  onClick={async () => {
                    const ok = await copyText(currentTitle)
                    if (ok) message.success('已复制当前标题')
                    else message.error('复制失败，请手动选中复制')
                  }}
                />
                {!includeCurrentTitle && (
                  <Text type="warning" style={{ fontSize: 11 }}>
                    (已去勾, AI 不会参考原标题, 完全从零拼新标题)
                  </Text>
                )}
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
              {/* 2026-05-02 老板拍：Antd Space wrap 在 modal 1100px 内不触发换行,
                  导致 3 个候选词挤一行。改 CSS Grid auto-fill 强制每行多列对齐 */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 6 }}>
                {preview.candidates.map(c => {
                  const orders = (c.organic_orders || 0) + (c.paid_orders || 0)
                  return (
                    <Checkbox
                      key={'cand-' + c.id}
                      checked={selectedCandidateIds.has(c.id)}
                      onChange={toggleSet(selectedCandidateIds, setSelectedCandidateIds).bind(null, c.id)}
                      style={{ marginInlineStart: 0 }}
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
              </div>
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
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 6 }}>
                {preview.category_top_keywords.map(k => {
                  const cross = k.looks_cross_category
                  return (
                    <Checkbox
                      key={'cat-' + k.keyword}
                      checked={selectedCategoryKeywords.has(k.keyword)}
                      onChange={toggleSet(selectedCategoryKeywords, setSelectedCategoryKeywords).bind(null, k.keyword)}
                      style={{ marginInlineStart: 0 }}
                    >
                      <Tooltip title={cross
                        ? '⚠️ 看起来含其他类目主词 (戒指/项链/胸针 等), 默认未勾; 若你确认本商品同样适用可手动勾上'
                        : `总订单 ${k.total_orders} / 总曝光 ${k.total_impressions} / 覆盖 ${k.product_count} 商品`}>
                        <span style={{ fontSize: 11, display: 'inline-block', lineHeight: 1.3 }}>
                          <div>
                            {k.keyword}
                            {cross && (
                              <Tag color="red" style={{ fontSize: 9, marginLeft: 4, padding: '0 4px', lineHeight: '14px', height: 14 }}>跨品类?</Tag>
                            )}
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
                  )
                })}
              </div>
            </div>
          )}

          {/* 手动输入关键词 (最多 3 个) */}
          <div style={{ marginBottom: 12, padding: '10px 12px', background: '#fff7e6', border: '1px solid #ffd591', borderRadius: 4 }}>
            <Space style={{ marginBottom: 6 }}>
              <Text strong style={{ fontSize: 12 }}>✏️ 手动输入关键词</Text>
              <Text type="warning" style={{ fontSize: 11, fontWeight: 500 }}>
                必须俄语
              </Text>
              <Text type="secondary" style={{ fontSize: 11 }}>
                可以不填; 看到竞品热门词系统里没的可以手填 (最多 3 个; 中文 / 拼音不会被 AI 识别融入)
              </Text>
            </Space>
            <Space size={6} wrap>
              {manualKeywords.map((kw, idx) => (
                <Input
                  key={'manual-' + idx}
                  value={kw}
                  onChange={(e) => {
                    const next = [...manualKeywords]
                    next[idx] = e.target.value
                    setManualKeywords(next)
                  }}
                  placeholder={`俄语关键词 ${idx + 1} (例: серьги жемчуг)`}
                  maxLength={50}
                  size="small"
                  style={{ width: 280, fontSize: 12 }}
                  allowClear
                />
              ))}
            </Space>
          </div>
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

          {result.manual_keywords?.length > 0 && (
            <Alert
              type={result.dropped_manual?.length ? 'error' : 'success'}
              showIcon
              style={{ marginBottom: 12 }}
              message={(
                <span>
                  ⚡ 你手动输入了 <strong>{result.manual_keywords.length}</strong> 个关键词
                  （最高优先级硬约束，AI 必须 100% 融入）：
                </span>
              )}
              description={(
                <div>
                  <Space size={4} wrap style={{ marginBottom: result.dropped_manual?.length ? 6 : 0 }}>
                    {result.manual_keywords.map((kw, i) => {
                      const dropped = result.dropped_manual?.includes(kw)
                      return (
                        <Tag key={i} color={dropped ? 'red' : 'green'} style={{ margin: 0, fontWeight: 600 }}>
                          {dropped ? '✗ ' : '✓ '}{kw}
                        </Tag>
                      )
                    })}
                  </Space>
                  {result.dropped_manual?.length > 0 && (
                    <Text type="danger" style={{ fontSize: 12, fontWeight: 600 }}>
                      ⚠️ AI 漏了 {result.dropped_manual.length} 个手填词（红色标签）—— 强烈建议点「重新生成」让 AI 重试，否则采用前请手动补回。
                    </Text>
                  )}
                </div>
              )}
            />
          )}

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
