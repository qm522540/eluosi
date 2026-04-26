import { useState, useEffect } from 'react'
import {
  Modal, Button, Typography, Space, Tag, Alert, Descriptions, Spin, message,
} from 'antd'
import {
  CopyOutlined, ThunderboltOutlined, RobotOutlined, CheckCircleOutlined,
} from '@ant-design/icons'
import { generateSeoDescription, applyGeneratedTitle } from '@/api/seo'
import { copyText } from '@/utils/clipboard'

const { Text, Paragraph } = Typography

/**
 * AI 商品描述生成 Modal
 *
 * 与 AiTitleModal 不同：
 * - 不让用户勾选候选词（后端自取全量缺词 Top 50）
 * - 展示长描述（多段，800-2000 字符）
 * - "启用新描述"调同一个 applyGeneratedTitle API（后端不查 content_type）
 */
const AiDescriptionModal = ({
  open, onClose,
  shopId, productId, productName, currentTitle, currentDescription,
}) => {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)

  useEffect(() => {
    if (open) setResult(null)
  }, [open, productId])

  const handleGenerate = async () => {
    if (!shopId || !productId) return
    setLoading(true)
    try {
      const r = await generateSeoDescription(shopId, productId, 50)
      if (r?.code === 0) {
        setResult(r.data)
      } else {
        message.error(r?.msg || '生成失败')
      }
    } catch (e) {
      message.error(e?.response?.data?.msg || e?.message || '网络错误')
    } finally {
      setLoading(false)
    }
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
      title: '确认启用新描述？',
      width: 580,
      icon: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
      content: (
        <div style={{ fontSize: 13, lineHeight: 1.7 }}>
          <div style={{ marginBottom: 12 }}>
            <Text type="secondary">将启用 {result.char_count} 字符的新描述（共融入 {result.included_keywords?.length || 0} 个候选词）。</Text>
          </div>
          <div style={{ background: '#fffbe6', padding: '8px 10px', borderRadius: 4, border: '1px solid #ffe58f' }}>
            <div style={{ marginBottom: 4 }}><strong>启用后系统会做：</strong></div>
            <div style={{ paddingLeft: 12 }}>
              ✓ 标记此描述为「已应用」<br/>
              ✓ 以本时间点为基线追踪 ROI（改前 / 改后曝光、订单、ROAS 对比）
            </div>
            <div style={{ marginTop: 8, color: '#d46b08' }}>
              ⚠ 本期暂不自动写回到 WB / Ozon 商品后台，请你<strong>手动</strong>到平台后台「编辑商品」粘贴新描述让平台真正生效
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
            message.success('已启用，ROI 基线已建立。请到平台后台粘贴新描述让平台生效。')
            onClose && onClose()
          } else {
            message.warning(`启用失败：${r?.msg || '未知错误'}`)
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
      title={<Space><RobotOutlined /><span>AI 生成商品描述</span></Space>}
      width={840}
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
        >
          开始生成（约 5-15 秒）
        </Button>,
      ]}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="描述启用后，健康诊断的「描述长度」维度会同步上涨（300-2000 字符为满分区间）"
      />
      <Descriptions size="small" column={1} bordered style={{ marginBottom: 12 }}>
        <Descriptions.Item label="商品">{productName || `ID ${productId}`}</Descriptions.Item>
        <Descriptions.Item label="当前俄语标题">
          {currentTitle
            ? <Text>{currentTitle}</Text>
            : <Text type="secondary">（空 / 未同步）</Text>}
        </Descriptions.Item>
        <Descriptions.Item label="当前俄语描述">
          {currentDescription
            ? (
              <div>
                <Paragraph
                  ellipsis={{ rows: 3, expandable: true, symbol: '展开' }}
                  style={{ marginBottom: 0, fontSize: 12, color: '#666' }}
                >
                  {currentDescription}
                </Paragraph>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  共 {currentDescription.length} 字符 · AI 将走「渐进改写」保留卖点
                </Text>
              </div>
            )
            : (
              <Text type="secondary">
                （空）AI 将从零写描述
              </Text>
            )}
        </Descriptions.Item>
        <Descriptions.Item label="喂给 GLM 的内容">
          <div style={{ fontSize: 12, lineHeight: 1.7 }}>
            <Text strong style={{ fontSize: 12 }}>📋 商品上下文（从 DB 抓取，空字段不会喂）</Text>
            <ul style={{ margin: '2px 0 6px 18px', paddingLeft: 0 }}>
              <li>平台风格规则（WB 紧凑 800-1200 字 / Ozon 长结构化 1200-2000 字）</li>
              <li>商品中文名 + 俄语名 + 品牌</li>
              <li><Text strong>类目路径</Text>（如 "Дом и сад / Товары для праздников / Шарик"）</li>
              <li>当前俄语标题 + 当前俄语描述（如有 → 走「渐进改写」保留卖点）</li>
              <li><Text strong>商品属性 variant_attrs</Text>（JSON 截断 1500 字符内，自然融入正文）</li>
            </ul>
            <Text strong style={{ fontSize: 12 }}>🔑 关键词</Text>
            <ul style={{ margin: '2px 0 6px 18px', paddingLeft: 0 }}>
              <li>缺词候选池 Top 50（按 score 降序，附 ROAS / 付费订单 / 自然订单 / 自然曝光 指标）</li>
              <li>必须保留的高价值词（标题/属性里已有 + 带订单或曝光≥20，最多 15 个）</li>
            </ul>
            <Text strong style={{ fontSize: 12 }}>📐 写死规则（system_prompt）</Text>
            <ul style={{ margin: '2px 0 0 18px', paddingLeft: 0 }}>
              <li>描述长度 800-2000 字符 / 段落分隔 / 标点正常使用</li>
              <li>关键词自然融入禁止堆砌、同义词换着用避免重复</li>
              <li><Text type="warning" strong>不能编造原数据没有的属性</Text>（如原品没说防水，AI 不能加 водостойкий）</li>
            </ul>
            <Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 6 }}>
              GLM 优先融入前 20-30 个高分候选词；低分长尾词若不契合可不融入。DB 里 NULL 的字段（比如品牌空、属性空）整段不会出现在 prompt 里。
            </Text>
          </div>
        </Descriptions.Item>
      </Descriptions>

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
                  已识别 <strong>{result.preserved_keywords.length}</strong> 个原标题/属性里的高价值词（带订单或曝光 ≥ 20），AI 已被要求保留：
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
