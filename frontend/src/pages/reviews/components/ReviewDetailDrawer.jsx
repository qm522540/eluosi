import { useState, useEffect } from 'react'
import {
  Drawer, Typography, Card, Tag, Rate, Space, Divider, message, Avatar, Button,
} from 'antd'
import { WomanOutlined, EyeOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { markReviewRead } from '@/api/reviews'
import AIReplyPanel from './AIReplyPanel'

const { Title, Text, Paragraph } = Typography

const PLATFORM_TAG = {
  wb:   { color: '#CB11AB', label: 'WB' },
  ozon: { color: '#005BFF', label: 'Ozon' },
}

const SENTIMENT_META = {
  positive: { color: 'success', label: '好评 😊' },
  neutral:  { color: 'default', label: '中评 😐' },
  negative: { color: 'error',   label: '差评 😞' },
  unknown:  { color: 'default', label: '未分析' },
}

const ReviewDetailDrawer = ({ open, review, shopPlatform, onClose }) => {
  const [marking, setMarking] = useState(false)
  const [changed, setChanged] = useState(false)

  useEffect(() => {
    // 抽屉打开时如果是 unread, 后台静默标已读 (用户看了就算读)
    if (open && review && review.status === 'unread') {
      markReviewRead(review.id).catch(() => {})
      setChanged(true)
    }
  }, [open, review])

  if (!review) return null

  const handleManualMarkRead = async () => {
    setMarking(true)
    try {
      await markReviewRead(review.id)
      message.success('已标记为已读')
      setChanged(true)
    } catch (e) {
      message.error(e?.message || '标记失败')
    } finally {
      setMarking(false)
    }
  }

  const onReplySent = () => {
    setChanged(true)
    // 不自动关 drawer, 让用户看到发送结果
  }

  const platformTag = PLATFORM_TAG[review.platform] || { color: 'default', label: review.platform }
  const sentMeta = SENTIMENT_META[review.sentiment] || SENTIMENT_META.unknown
  const isReplied = review.status === 'replied' || review.status === 'auto_replied'

  return (
    <Drawer
      title={
        <Space size={8}>
          <Tag color={platformTag.color} style={{ color: '#fff' }}>{platformTag.label}</Tag>
          <span>评价详情</span>
          <Tag color={sentMeta.color}>{sentMeta.label}</Tag>
          {isReplied && <Tag color="success">已回复</Tag>}
        </Space>
      }
      open={open}
      onClose={() => onClose(changed)}
      width={760}
    >
      {/* 买家评价 */}
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space direction="vertical" style={{ width: '100%' }} size={6}>
          <Space size={8} style={{ alignItems: 'center' }}>
            <Avatar size={32} icon={<WomanOutlined />}
                    style={{ background: '#f0a8b0' }} />
            <Text strong style={{ fontSize: 14 }}>
              {review.customer_name || '匿名买家'}
            </Text>
            <Rate disabled value={review.rating} style={{ fontSize: 14 }} />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {review.created_at_platform
                ? dayjs(review.created_at_platform).format('YYYY-MM-DD HH:mm')
                : '—'}
            </Text>
          </Space>

          {review.platform_product_name && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              📦 {review.platform_product_name} {review.platform_sku_id && `(SKU ${review.platform_sku_id})`}
            </Text>
          )}

          <Divider style={{ margin: '8px 0' }} />

          <div>
            <Text type="secondary" style={{ fontSize: 11 }}>俄语原文</Text>
            <Paragraph style={{ marginTop: 2, marginBottom: 6, fontSize: 14 }}>
              {review.content_ru}
            </Paragraph>
          </div>

          <div>
            <Text type="secondary" style={{ fontSize: 11 }}>中文翻译</Text>
            <Paragraph style={{ marginTop: 2, marginBottom: 0, fontSize: 13, color: '#666' }}>
              {review.content_zh || <span style={{ color: '#ccc' }}>翻译中...</span>}
            </Paragraph>
          </div>

          {review.existing_reply_ru && (
            <>
              <Divider style={{ margin: '8px 0' }} />
              <div>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  ✓ 已有平台回复 {review.existing_reply_at && `(${dayjs(review.existing_reply_at).format('MM-DD HH:mm')})`}
                </Text>
                <Paragraph style={{ marginTop: 2, marginBottom: 0, fontSize: 13,
                                    background: '#f6ffed', padding: '6px 10px', borderRadius: 4 }}>
                  {review.existing_reply_ru}
                </Paragraph>
              </div>
            </>
          )}
        </Space>
      </Card>

      {/* AI 回复面板 */}
      {!isReplied ? (
        <AIReplyPanel
          review={review}
          shopPlatform={shopPlatform}
          onReplySent={onReplySent}
        />
      ) : (
        <Card size="small">
          <Text type="secondary" style={{ fontSize: 12 }}>
            该评价已回复. 如需重新回复, 请先到平台后台撤回旧回复.
          </Text>
          <div style={{ marginTop: 8 }}>
            <Button size="small" icon={<EyeOutlined />}
                    loading={marking}
                    onClick={handleManualMarkRead}
                    disabled={review.status !== 'unread'}>
              标为已读
            </Button>
          </div>
        </Card>
      )}
    </Drawer>
  )
}

export default ReviewDetailDrawer
