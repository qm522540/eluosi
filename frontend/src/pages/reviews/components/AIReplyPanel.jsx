import { useState } from 'react'
import {
  Card, Typography, Input, Button, Space, Divider, Modal, message, Tag,
} from 'antd'
import {
  RobotOutlined, ReloadOutlined, SendOutlined, EditOutlined,
} from '@ant-design/icons'
import { generateReply, sendReply } from '@/api/reviews'

const { Text, Paragraph } = Typography
const { TextArea } = Input

const AIReplyPanel = ({ review, shopPlatform, onReplySent }) => {
  const [generating, setGenerating] = useState(false)
  const [sending, setSending] = useState(false)
  const [reply, setReply] = useState(null)            // {reply_id, draft_ru, draft_zh, generated_count}
  const [customHint, setCustomHint] = useState('')
  const [editingRu, setEditingRu] = useState(false)
  const [finalRu, setFinalRu] = useState('')

  const handleGenerate = async (regenerate = false) => {
    setGenerating(true)
    try {
      const r = await generateReply(review.id, customHint)
      const d = r.data
      setReply(d)
      setFinalRu(d.draft_ru)
      setEditingRu(false)
      message.success(regenerate
        ? `已重新生成 (第 ${d.generated_count} 版)`
        : `已生成草稿`,
      )
    } catch (e) {
      message.error(e?.message || '生成失败', 6)
    } finally {
      setGenerating(false)
    }
  }

  const handleSend = () => {
    if (!reply) { message.warning('请先生成草稿'); return }
    const text = (finalRu || '').trim() || reply.draft_ru
    if (!text) { message.warning('回复内容为空'); return }

    Modal.confirm({
      title: '确认发送回复',
      content: (
        <div>
          <Text type="secondary" style={{ fontSize: 12 }}>
            将以俄语发送到{shopPlatform === 'wb' ? ' Wildberries ' : ' Ozon '}平台,
            发送后无法撤回 (需到平台后台修改). 确认?
          </Text>
          <div style={{
            marginTop: 8, padding: 8,
            background: '#fafafa', borderRadius: 4,
            fontSize: 13, lineHeight: 1.5, maxHeight: 150, overflow: 'auto',
          }}>{text}</div>
        </div>
      ),
      okText: '确认发送',
      cancelText: '取消',
      onOk: async () => {
        setSending(true)
        try {
          const editedFinal = (finalRu || '').trim() && finalRu !== reply.draft_ru
            ? finalRu
            : null
          const r = await sendReply(review.id, reply.reply_id, editedFinal)
          message.success(r.data?.msg || '发送成功')
          onReplySent?.(r.data)
        } catch (e) {
          message.error(e?.message || '发送失败', 6)
        } finally {
          setSending(false)
        }
      },
    })
  }

  return (
    <Card size="small"
          title={
            <Space size={6}>
              <RobotOutlined style={{ color: '#7c6cf0' }} />
              <span>AI 回复</span>
              {reply && reply.generated_count > 1 && (
                <Tag color="orange">第 {reply.generated_count} 版</Tag>
              )}
            </Space>
          }>
      {!reply ? (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            点击生成俄语回复草稿 + 中文翻译. 可在下方"自定义重点"输入想强调的信息.
          </Text>
          <TextArea
            placeholder="(可选) 自定义重点 — 例如: 提一下 30 天无理由退换 / 强调免费物流..."
            value={customHint}
            onChange={e => setCustomHint(e.target.value)}
            maxLength={500} showCount
            rows={2}
          />
          <Button type="primary" icon={<RobotOutlined />}
                  loading={generating}
                  onClick={() => handleGenerate(false)}>
            生成 AI 回复
          </Button>
        </Space>
      ) : (
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          {/* 中文翻译 */}
          <div>
            <Text type="secondary" style={{ fontSize: 11 }}>中文翻译 (给老板看)</Text>
            <Paragraph style={{
              marginTop: 2, marginBottom: 0, fontSize: 13, color: '#666',
              background: '#f5f7ff', padding: '6px 10px', borderRadius: 4,
            }}>
              {reply.draft_zh || <span style={{ color: '#ccc' }}>翻译中...</span>}
            </Paragraph>
          </div>

          {/* 俄语草稿 */}
          <div>
            <Space size={4} style={{ marginBottom: 4 }}>
              <Text type="secondary" style={{ fontSize: 11 }}>俄语回复 (将发送到平台)</Text>
              {!editingRu && (
                <Button size="small" type="link" icon={<EditOutlined />}
                        style={{ fontSize: 11, padding: '0 4px', height: 'auto' }}
                        onClick={() => setEditingRu(true)}>
                  编辑
                </Button>
              )}
            </Space>
            {editingRu ? (
              <TextArea value={finalRu}
                        onChange={e => setFinalRu(e.target.value)}
                        maxLength={2000} showCount rows={5}
                        autoFocus />
            ) : (
              <Paragraph style={{
                marginBottom: 0, fontSize: 13,
                background: '#fff7e6', padding: '8px 10px', borderRadius: 4,
                whiteSpace: 'pre-wrap',
              }}>
                {finalRu || reply.draft_ru}
              </Paragraph>
            )}
          </div>

          <Divider style={{ margin: '6px 0' }} />

          {/* 重新生成区 */}
          <div>
            <Text type="secondary" style={{ fontSize: 11 }}>
              不满意? 输入新的重点重新生成:
            </Text>
            <TextArea
              placeholder="例如: 语气更亲切一点 / 加上联系方式 / 提一下圣诞节优惠..."
              value={customHint}
              onChange={e => setCustomHint(e.target.value)}
              maxLength={500} showCount
              rows={2}
              style={{ marginTop: 4 }}
            />
            <Button size="small" icon={<ReloadOutlined />}
                    loading={generating}
                    onClick={() => handleGenerate(true)}
                    style={{ marginTop: 6 }}>
              重新生成
            </Button>
          </div>

          <Divider style={{ margin: '6px 0' }} />

          <Space>
            <Button type="primary" icon={<SendOutlined />}
                    loading={sending}
                    onClick={handleSend}
                    danger={false}>
              发送到{shopPlatform === 'wb' ? ' WB ' : ' Ozon '}
            </Button>
            <Text type="secondary" style={{ fontSize: 11 }}>
              发送后无法撤回 (需平台后台改)
            </Text>
          </Space>
        </Space>
      )}
    </Card>
  )
}

export default AIReplyPanel
