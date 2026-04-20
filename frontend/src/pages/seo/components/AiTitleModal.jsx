import { useState, useEffect } from 'react'
import {
  Modal, Button, Typography, Space, Tag, Alert, Descriptions, Divider, Spin, message,
} from 'antd'
import {
  CopyOutlined, ThunderboltOutlined, RobotOutlined,
} from '@ant-design/icons'
import { generateSeoTitle } from '@/api/seo'

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

  // 每次重新打开清空上一次结果
  useEffect(() => {
    if (open) setResult(null)
  }, [open, productId])

  const handleGenerate = async () => {
    if (!shopId || !productId || !selectedCandidates?.length) return
    setLoading(true)
    try {
      const ids = selectedCandidates.map(c => c.id)
      const res = await generateSeoTitle(shopId, productId, ids)
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
    try {
      await navigator.clipboard.writeText(result.new_title)
      message.success('已复制到剪贴板，去商品列表「编辑商品」粘贴到标题即可')
    } catch {
      message.error('复制失败，请手动选中文字复制')
    }
  }

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={<Space><RobotOutlined /><span>AI 融合关键词生成新标题</span></Space>}
      width={720}
      destroyOnClose
      footer={result ? [
        <Button key="close" onClick={onClose}>关闭</Button>,
        <Button key="regen" icon={<ThunderboltOutlined />} onClick={handleGenerate} loading={loading}>
          重新生成
        </Button>,
        <Button key="copy" type="primary" icon={<CopyOutlined />} onClick={handleCopy}>
          一键复制新标题
        </Button>,
      ] : [
        <Button key="cancel" onClick={onClose}>取消</Button>,
        <Button
          key="gen"
          type="primary"
          icon={<ThunderboltOutlined />}
          onClick={handleGenerate}
          loading={loading}
          disabled={!selectedCandidates?.length}
        >
          开始生成（约 5-15 秒）
        </Button>,
      ]}
    >
      <Descriptions size="small" column={1} bordered style={{ marginBottom: 12 }}>
        <Descriptions.Item label="商品">{productName || `ID ${productId}`}</Descriptions.Item>
        <Descriptions.Item label="当前俄语标题">
          {currentTitle
            ? <Text copyable>{currentTitle}</Text>
            : <Text type="secondary">（空 / 未同步）</Text>}
        </Descriptions.Item>
        <Descriptions.Item label={`选中反哺词 (${selectedCandidates?.length || 0})`}>
          <Space size={4} wrap>
            {(selectedCandidates || []).slice(0, 30).map(c => (
              <Tag key={c.id} color="blue">{c.keyword}</Tag>
            ))}
            {selectedCandidates?.length > 30 && <Text type="secondary">…还有 {selectedCandidates.length - 30} 个</Text>}
          </Space>
        </Descriptions.Item>
      </Descriptions>

      {loading && (
        <div style={{ textAlign: 'center', padding: '40px 0' }}>
          <Spin size="large" />
          <div style={{ marginTop: 12, color: '#999' }}>AI 正在融合关键词（走 GLM 俄语模型）…</div>
        </div>
      )}

      {!loading && result && (
        <>
          <Divider>AI 生成结果</Divider>

          <Alert
            type="success"
            showIcon
            style={{ marginBottom: 12 }}
            message={<Text strong>新俄语标题：</Text>}
            description={
              <Paragraph
                copyable={{ text: result.new_title }}
                style={{ fontSize: 15, marginBottom: 0, lineHeight: 1.6 }}
              >
                {result.new_title}
              </Paragraph>
            }
          />

          {result.reasoning && (
            <Alert
              type="info"
              showIcon={false}
              style={{ marginBottom: 12 }}
              message={<Text type="secondary">AI 决策说明</Text>}
              description={result.reasoning}
            />
          )}

          <Descriptions size="small" column={2} style={{ marginTop: 8 }}>
            <Descriptions.Item label="模型">{result.ai_model?.toUpperCase()}</Descriptions.Item>
            <Descriptions.Item label="耗时">{result.duration_ms} ms</Descriptions.Item>
            <Descriptions.Item label="Token">
              {result.tokens?.prompt} + {result.tokens?.completion} = {result.tokens?.total}
            </Descriptions.Item>
            <Descriptions.Item label="实际用词">
              {result.included_keywords?.length || 0} 个
            </Descriptions.Item>
          </Descriptions>

          {result.included_keywords?.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <Text type="secondary" style={{ marginRight: 8 }}>用到的词：</Text>
              <Space size={4} wrap>
                {result.included_keywords.map((kw, i) => (
                  <Tag key={i} color="green">{kw}</Tag>
                ))}
              </Space>
            </div>
          )}

          <Alert
            type="warning"
            showIcon
            style={{ marginTop: 16 }}
            message="本期仅生成建议，不会直接改商品标题"
            description="请复制新标题，去「商品管理 → 商品列表 → 编辑」手动粘贴。三期会加「一键写回商品」。"
          />
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
