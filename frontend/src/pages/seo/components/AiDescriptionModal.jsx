import { useState, useEffect, useMemo } from 'react'
import {
  Modal, Button, Typography, Space, Tag, Alert, Descriptions, Spin, message,
  Input, Checkbox, Tooltip, Divider,
} from 'antd'
import {
  CopyOutlined, ThunderboltOutlined, RobotOutlined, CheckCircleOutlined, ClearOutlined,
} from '@ant-design/icons'
import {
  generateSeoDescription, applyGeneratedTitle, getShopBrandPhilosophy,
  previewSeoDescriptionInputs,
} from '@/api/seo'
import { copyText } from '@/utils/clipboard'

const { Text, Paragraph } = Typography

/**
 * AI 商品描述生成 Modal — 用户可勾选哪些字段/属性/关键词喂给 AI。
 *
 * 默认全选, 取消勾选的项在生成时不传给后端 (走 excluded_* 参数)。
 * 4 个分组:
 *   1. 上下文字段 (品牌理念/中文名/俄语名/品牌/类目/标题/描述)
 *   2. 商品属性 (Ozon 黑名单已过滤后的全集)
 *   3. 同类目热门关键词 Top 30 (跨商品聚合)
 *   4. 本商品热门关键词 Top 10
 */
const AiDescriptionModal = ({
  open, onClose,
  shopId, productId, productName, currentTitle, currentDescription,
}) => {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)

  // preview 数据 (全集)
  const [preview, setPreview] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)

  // 用户勾选状态 (默认全选)
  const [selectedContextKeys, setSelectedContextKeys] = useState(new Set())
  const [selectedAttrIds, setSelectedAttrIds] = useState(new Set())
  const [selectedKeywords, setSelectedKeywords] = useState(new Set())

  // 品牌理念 (店铺级共享, 文本框可编辑)
  const [brandPhilosophy, setBrandPhilosophy] = useState('')
  const [philosophyDirty, setPhilosophyDirty] = useState(false)

  useEffect(() => {
    if (open) setResult(null)
  }, [open, productId])

  // 打开时:并发拉品牌理念 + preview 数据
  useEffect(() => {
    if (!open || !shopId || !productId) return
    setPreviewLoading(true)
    setPhilosophyDirty(false)

    Promise.all([
      getShopBrandPhilosophy(shopId).catch(() => ({ data: { brand_philosophy: '' } })),
      previewSeoDescriptionInputs(shopId, productId).catch((e) => {
        message.error(e?.response?.data?.msg || '加载预览数据失败')
        return null
      }),
    ]).then(([bpRes, prevRes]) => {
      setBrandPhilosophy(bpRes?.data?.brand_philosophy || '')
      if (prevRes?.data) {
        setPreview(prevRes.data)
        // 默认全选
        setSelectedContextKeys(new Set((prevRes.data.context_fields || []).map(f => f.key)))
        setSelectedAttrIds(new Set((prevRes.data.attrs || []).map(a => a.id)))
        const allKws = [
          ...(prevRes.data.category_top_keywords || []).map(k => k.keyword),
          ...(prevRes.data.product_top_keywords || []).map(k => k.keyword),
        ]
        setSelectedKeywords(new Set(allKws))
      }
    }).finally(() => setPreviewLoading(false))
  }, [open, shopId, productId])

  // 计算最终要传后端的 excluded
  const excluded = useMemo(() => {
    if (!preview) return { contextKeys: [], attrIds: [], keywords: [] }
    const allCtxKeys = (preview.context_fields || []).map(f => f.key)
    const allAttrIds = (preview.attrs || []).map(a => a.id)
    const allKws = [
      ...(preview.category_top_keywords || []).map(k => k.keyword),
      ...(preview.product_top_keywords || []).map(k => k.keyword),
    ]
    return {
      contextKeys: allCtxKeys.filter(k => !selectedContextKeys.has(k)),
      attrIds: allAttrIds.filter(id => !selectedAttrIds.has(id)),
      keywords: allKws.filter(k => !selectedKeywords.has(k)),
    }
  }, [preview, selectedContextKeys, selectedAttrIds, selectedKeywords])

  // 帮手:切换 Set 里的项
  const toggleSet = (set, setter) => (val) => {
    const next = new Set(set)
    if (next.has(val)) next.delete(val); else next.add(val)
    setter(next)
  }

  // 全选/反选
  const toggleAllAttrs = () => {
    if (selectedAttrIds.size === (preview?.attrs || []).length) {
      setSelectedAttrIds(new Set())
    } else {
      setSelectedAttrIds(new Set((preview?.attrs || []).map(a => a.id)))
    }
  }
  const toggleAllCatKws = () => {
    const list = (preview?.category_top_keywords || []).map(k => k.keyword)
    const allSelected = list.every(k => selectedKeywords.has(k))
    const next = new Set(selectedKeywords)
    if (allSelected) list.forEach(k => next.delete(k))
    else list.forEach(k => next.add(k))
    setSelectedKeywords(next)
  }
  const toggleAllProdKws = () => {
    const list = (preview?.product_top_keywords || []).map(k => k.keyword)
    const allSelected = list.every(k => selectedKeywords.has(k))
    const next = new Set(selectedKeywords)
    if (allSelected) list.forEach(k => next.delete(k))
    else list.forEach(k => next.add(k))
    setSelectedKeywords(next)
  }

  const handleGenerate = async () => {
    if (!shopId || !productId) return
    setLoading(true)
    try {
      // 用户动过文本框就传当前值, 没动则不传 (后端用 shops 表现值)
      const bp = philosophyDirty ? brandPhilosophy : undefined
      const r = await generateSeoDescription(shopId, productId, {
        brandPhilosophy: bp,
        excluded,
      })
      if (r?.code === 0) {
        setResult(r.data)
        if (r.data?.brand_philosophy !== undefined) {
          setBrandPhilosophy(r.data.brand_philosophy)
          setPhilosophyDirty(false)
        }
      } else {
        message.error(r?.msg || '生成失败')
      }
    } catch (e) {
      message.error(e?.response?.data?.msg || e?.message || '网络错误')
    } finally {
      setLoading(false)
    }
  }

  const handleClearPhilosophy = () => {
    setBrandPhilosophy('')
    setPhilosophyDirty(true)
    message.info('已清空,点「开始生成」后该店铺品牌理念会被删除')
  }

  const handleCopy = async () => {
    if (!result?.new_description) return
    const ok = await copyText(result.new_description)
    if (ok) message.success('已复制描述到剪贴板，去商品列表「编辑商品」粘贴到描述字段')
    else message.error('复制失败，请手动选中文字复制')
  }

  const handleApply = () => {
    if (!result?.generated_content_id) return
    Modal.confirm({
      title: '确认启用新描述?',
      width: 600,
      icon: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
      content: (
        <div style={{ fontSize: 13, lineHeight: 1.7 }}>
          <div style={{ marginBottom: 12 }}>
            <Text type="secondary">将启用 {result.char_count} 字符的新描述 (融入 {result.included_keywords?.length || 0} 个候选词)。</Text>
          </div>
          <div style={{ background: '#fffbe6', padding: '8px 10px', borderRadius: 4, border: '1px solid #ffe58f' }}>
            <div style={{ marginBottom: 4 }}><strong>启用后系统会做:</strong></div>
            <div style={{ paddingLeft: 12 }}>
              ✓ 改本地数据库描述为新描述 (健康诊断等页面立即同步)<br/>
              ✓ 调用 <strong>Ozon API</strong> 把平台后台商品描述也改成新描述 (1-5 分钟生效)<br/>
              ✓ 标记此描述为「已应用」, 以本时间点为基线追踪 ROI 对比
            </div>
            <div style={{ marginTop: 8, color: '#d46b08' }}>
              ⚠ <strong>WB 平台</strong>暂不支持 API 写回, 请手动到 WB 后台粘贴新描述
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
              message.warning(`本地描述已改, 但 Ozon API 写回失败: ${wb.msg} — 请手动到 Ozon 后台改`, 8)
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

  // 上下文字段中, 品牌理念走单独的 TextArea 渲染, 其余字段一行一个 checkbox
  const ctxFields = (preview?.context_fields || []).filter(f => f.key !== 'brand_philosophy')

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={<Space><RobotOutlined /><span>AI 生成商品描述</span></Space>}
      width={1200}
      destroyOnClose
      footer={result ? [
        <Button key="close" onClick={onClose}>关闭</Button>,
        <Button key="regen" icon={<ThunderboltOutlined />} onClick={handleGenerate} loading={loading}>
          重新生成
        </Button>,
        <Button key="copy" icon={<CopyOutlined />} onClick={handleCopy}>
          一键复制新描述
        </Button>,
        <Button
          key="apply"
          type="primary"
          icon={<CheckCircleOutlined />}
          onClick={handleApply}
        >
          启用新描述
        </Button>,
      ] : [
        <Button key="cancel" onClick={onClose}>取消</Button>,
        <Button
          key="gen"
          type="primary"
          icon={<ThunderboltOutlined />}
          onClick={handleGenerate}
          loading={loading}
          disabled={previewLoading}
        >
          开始生成（约 5-15 秒）
        </Button>,
      ]}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="勾选哪些数据喂给 AI ─ 默认全选, 去掉勾就不传给 AI。生成后描述启用, 健康诊断「描述长度」维度会同步上涨。"
      />

      {previewLoading ? (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin tip="加载预览数据..." />
        </div>
      ) : preview ? (
        <>
          {/* === 1. 上下文字段 (除品牌理念外) === */}
          {ctxFields.length > 0 && (
            <div style={{ marginBottom: 12, padding: '10px 12px', border: '1px solid #e8e8e8', borderRadius: 4 }}>
              <div style={{ marginBottom: 6 }}>
                <Text strong style={{ fontSize: 12 }}>📋 商品上下文 ({ctxFields.length} 项)</Text>
              </div>
              {ctxFields.map(f => (
                <div key={f.key} style={{ marginBottom: 4 }}>
                  <Checkbox
                    checked={selectedContextKeys.has(f.key)}
                    onChange={toggleSet(selectedContextKeys, setSelectedContextKeys).bind(null, f.key)}
                  >
                    <Text strong style={{ fontSize: 12 }}>{f.label}: </Text>
                    <Text style={{ fontSize: 12, color: '#666' }}>
                      {f.value.length > 120 ? f.value.slice(0, 120) + '…' : f.value}
                    </Text>
                  </Checkbox>
                </div>
              ))}
            </div>
          )}

          {/* === 3. 商品属性 (横排) === */}
          {(preview.attrs || []).length > 0 && (
            <div style={{ marginBottom: 12, padding: '10px 12px', border: '1px solid #e8e8e8', borderRadius: 4 }}>
              <Space style={{ marginBottom: 6 }}>
                <Text strong style={{ fontSize: 12 }}>
                  🏷️ 商品属性 ({selectedAttrIds.size} / {preview.attrs.length})
                </Text>
                <Button size="small" type="link" onClick={toggleAllAttrs} style={{ fontSize: 11, padding: 0 }}>
                  {selectedAttrIds.size === preview.attrs.length ? '全不选' : '全选'}
                </Button>
              </Space>
              <Space size={[6, 6]} wrap>
                {preview.attrs.map(a => {
                  const label = `${a.name_zh || a.name_ru || `#${a.id}`}: ${a.value_ru}`
                  const short = label.length > 40 ? label.slice(0, 40) + '…' : label
                  return (
                    <Checkbox
                      key={a.id}
                      checked={selectedAttrIds.has(a.id)}
                      onChange={toggleSet(selectedAttrIds, setSelectedAttrIds).bind(null, a.id)}
                    >
                      <Tooltip title={label}>
                        <span style={{ fontSize: 11 }}>{short}</span>
                      </Tooltip>
                    </Checkbox>
                  )
                })}
              </Space>
            </div>
          )}

          {/* === 4. 同类目热门关键词 (横排) === */}
          {(preview.category_top_keywords || []).length > 0 && (
            <div style={{ marginBottom: 12, padding: '10px 12px', border: '1px solid #e8e8e8', borderRadius: 4 }}>
              <Space style={{ marginBottom: 6 }}>
                <Text strong style={{ fontSize: 12 }}>
                  🔥 同类目热门关键词 (
                  {preview.category_top_keywords.filter(k => selectedKeywords.has(k.keyword)).length}
                  {' / '}
                  {preview.category_top_keywords.length})
                </Text>
                <Text type="secondary" style={{ fontSize: 11 }}>跨商品聚合, 按订单+曝光降序</Text>
                <Button size="small" type="link" onClick={toggleAllCatKws} style={{ fontSize: 11, padding: 0 }}>
                  {preview.category_top_keywords.every(k => selectedKeywords.has(k.keyword)) ? '全不选' : '全选'}
                </Button>
              </Space>
              <Space size={[6, 6]} wrap>
                {preview.category_top_keywords.map(k => (
                  <Checkbox
                    key={'cat-' + k.keyword}
                    checked={selectedKeywords.has(k.keyword)}
                    onChange={toggleSet(selectedKeywords, setSelectedKeywords).bind(null, k.keyword)}
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
                          <div style={{ fontSize: 10, color: '#1677ff' }}>
                            {k.keyword_zh}
                          </div>
                        )}
                      </span>
                    </Tooltip>
                  </Checkbox>
                ))}
              </Space>
            </div>
          )}

          {/* === 4. 本商品热门关键词 (横排) === */}
          {(preview.product_top_keywords || []).length > 0 && (
            <div style={{ marginBottom: 12, padding: '10px 12px', border: '1px solid #e8e8e8', borderRadius: 4 }}>
              <Space style={{ marginBottom: 6 }}>
                <Text strong style={{ fontSize: 12 }}>
                  ⭐ 本商品热门关键词 (
                  {preview.product_top_keywords.filter(k => selectedKeywords.has(k.keyword)).length}
                  {' / '}
                  {preview.product_top_keywords.length})
                </Text>
                <Text type="secondary" style={{ fontSize: 11 }}>本商品订单+曝光降序</Text>
                <Button size="small" type="link" onClick={toggleAllProdKws} style={{ fontSize: 11, padding: 0 }}>
                  {preview.product_top_keywords.every(k => selectedKeywords.has(k.keyword)) ? '全不选' : '全选'}
                </Button>
              </Space>
              <Space size={[6, 6]} wrap>
                {preview.product_top_keywords.map(k => {
                  const orders = (k.organic_orders || 0) + (k.paid_orders || 0)
                  return (
                    <Checkbox
                      key={'prod-' + k.keyword}
                      checked={selectedKeywords.has(k.keyword)}
                      onChange={toggleSet(selectedKeywords, setSelectedKeywords).bind(null, k.keyword)}
                    >
                      <Tooltip title={`score ${k.score?.toFixed?.(1) || '-'} / 自然曝光 ${k.organic_impressions} / 订单 ${orders}`}>
                        <span style={{ fontSize: 11, display: 'inline-block', lineHeight: 1.3 }}>
                          <div>
                            {k.keyword}
                            <Text type="secondary" style={{ fontSize: 10, marginLeft: 4 }}>
                              ({k.organic_impressions}曝/{orders}单)
                            </Text>
                          </div>
                          {k.keyword_zh && k.keyword_zh !== k.keyword && (
                            <div style={{ fontSize: 10, color: '#1677ff' }}>
                              {k.keyword_zh}
                            </div>
                          )}
                        </span>
                      </Tooltip>
                    </Checkbox>
                  )
                })}
              </Space>
            </div>
          )}

          {/* === 5. 自定义输入 (店铺级共享, 自由文本) === */}
          <div style={{ marginBottom: 12, padding: '10px 12px', background: '#fff7e6', borderRadius: 4, border: '1px solid #ffd591' }}>
            <Space style={{ marginBottom: 6 }}>
              <Checkbox
                checked={selectedContextKeys.has('brand_philosophy')}
                onChange={toggleSet(selectedContextKeys, setSelectedContextKeys).bind(null, 'brand_philosophy')}
              >
                <Text strong style={{ fontSize: 12 }}>✏️ 自定义输入</Text>
              </Checkbox>
              <Text type="secondary" style={{ fontSize: 11 }}>
                (店铺级共享, 同店所有商品共用; 文本框可改, 想给 AI 加什么调性/风格/卖点取舍指令都行; 勾掉即不喂 AI)
              </Text>
              {brandPhilosophy && (
                <Button size="small" type="text" danger icon={<ClearOutlined />}
                        onClick={handleClearPhilosophy} style={{ fontSize: 11 }}>
                  清空
                </Button>
              )}
            </Space>
            <Input.TextArea
              value={brandPhilosophy}
              onChange={(e) => { setBrandPhilosophy(e.target.value); setPhilosophyDirty(true) }}
              placeholder="例如:专注极简北欧风首饰,女性日常通勤百搭,材质天然环保 / 描述要有节日仪式感 / 文案少用感叹号"
              maxLength={500}
              showCount
              rows={2}
              style={{ fontSize: 12 }}
            />
            {philosophyDirty && (
              <Text type="warning" style={{ fontSize: 11 }}>
                ⚠ 已修改, 点「开始生成」后会自动保存到该店铺
              </Text>
            )}
          </div>
        </>
      ) : (
        <Alert type="warning" message="预览数据加载失败,无法选择字段" />
      )}

      {loading && (
        <div style={{ textAlign: 'center', padding: '40px 0' }}>
          <Spin size="large" />
          <div style={{ marginTop: 12, color: '#999' }}>
            AI 正在写商品描述（走 GLM，需要 5-15 秒）…
          </div>
        </div>
      )}

      {!loading && result && (
        <>
          <Divider style={{ margin: '12px 0' }} />
          <Alert
            type="success"
            showIcon
            style={{ marginBottom: 12 }}
            message={(
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                <span style={{ fontWeight: 500 }}>新描述（{result.char_count} 字符）</span>
                <CopyOutlined
                  style={{ cursor: 'pointer', color: '#1677ff' }}
                  onClick={handleCopy}
                />
              </div>
            )}
            description={(
              <Paragraph
                style={{
                  fontSize: 13, marginBottom: 0, lineHeight: 1.7,
                  whiteSpace: 'pre-wrap',
                  background: '#fff', padding: 10, borderRadius: 4,
                  border: '1px solid #e6f4d8',
                  maxHeight: 320, overflowY: 'auto',
                }}
              >
                {result.new_description}
              </Paragraph>
            )}
          />

          {result.reasoning && (
            <Alert
              type="info"
              showIcon={false}
              style={{ marginBottom: 12, background: '#fafafa' }}
              message={(
                <Text type="secondary" style={{ fontSize: 12 }}>
                  <strong>AI 思路：</strong>{result.reasoning}
                </Text>
              )}
            />
          )}

          <div style={{ marginBottom: 12, padding: '8px 10px', background: '#fafafa', borderRadius: 4 }}>
            <Text type="secondary" style={{ fontSize: 11 }}>
              模型 <Text strong>{result.ai_model}</Text> · 耗时 <Text strong>{result.duration_ms} ms</Text> · Token <Text strong>{result.tokens?.total ?? '-'}</Text>
            </Text>
            {result.included_keywords?.length > 0 && (
              <div style={{ marginTop: 6 }}>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  实际融入 {result.included_keywords.length} 个关键词：
                </Text>
                <Space size={4} wrap style={{ marginTop: 4 }}>
                  {result.included_keywords.slice(0, 30).map((kw, i) => (
                    <Tag key={i} color="blue" style={{ fontSize: 11 }}>{kw}</Tag>
                  ))}
                  {result.included_keywords.length > 30 && (
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      …还有 {result.included_keywords.length - 30} 个
                    </Text>
                  )}
                </Space>
              </div>
            )}
          </div>

          {result.preserved_keywords?.length > 0 && (
            <Alert
              type={result.dropped_preserve?.length > 0 ? 'warning' : 'info'}
              showIcon
              style={{ marginBottom: 8 }}
              message={
                <Text style={{ fontSize: 12 }}>
                  本商品高价值词 <strong>{result.preserved_keywords.length}</strong> 个 (带过订单/曝光≥20), AI 已被要求保留：
                </Text>
              }
              description={
                <Space size={4} wrap style={{ marginTop: 4 }}>
                  {result.preserved_keywords.map((kw, i) => {
                    const dropped = result.dropped_preserve?.includes(kw)
                    return (
                      <Tag
                        key={i}
                        color={dropped ? 'red' : 'green'}
                        style={{ fontSize: 11 }}
                      >
                        {dropped ? '✗' : '✓'} {kw}
                      </Tag>
                    )
                  })}
                </Space>
              }
            />
          )}

          <div style={{ marginTop: 8, fontSize: 12, color: '#999' }}>
            一期仅生成建议，请复制新描述到「商品管理 → 编辑商品」手动粘贴。
          </div>
        </>
      )}
    </Modal>
  )
}

export default AiDescriptionModal
