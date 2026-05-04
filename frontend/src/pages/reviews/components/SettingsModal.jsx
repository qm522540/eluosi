import { useState, useEffect } from 'react'
import {
  Modal, Form, Switch, Select, Input, Slider, Typography, message, Spin, Divider, Space, Tag,
} from 'antd'
import { getReviewSettings, updateReviewSettings } from '@/api/reviews'

const { Text, Paragraph } = Typography
const { TextArea } = Input

const TONE_OPTIONS = [
  { value: 'friendly', label: '友好 + 温暖 (推荐)', desc: '亲切自然 / 用 emoji / 服务感强 — 默认值' },
  { value: 'warm',     label: '温暖 (情感更浓)', desc: '更感性 / 多用 💛 ✨ / 适合女装/家居/美妆' },
  { value: 'formal',   label: '正式 (商务感)', desc: '克制礼貌 / 不用 emoji / 适合 B2B/电子' },
]

const SettingsModal = ({ open, shopId, shopName, onClose }) => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open || !shopId) return
    setLoading(true)
    getReviewSettings(shopId)
      .then(r => {
        const d = r.data || {}
        form.setFieldsValue({
          auto_reply_enabled: !!d.auto_reply_enabled,
          auto_reply_rating_floor: d.auto_reply_rating_floor ?? 4,
          reply_tone: d.reply_tone || 'friendly',
          brand_signature: d.brand_signature || '',
          custom_prompt_extra: d.custom_prompt_extra || '',
        })
      })
      .catch(e => {
        message.error(e?.message || '加载设置失败')
      })
      .finally(() => setLoading(false))
  }, [open, shopId, form])

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      await updateReviewSettings(shopId, values)
      message.success('设置已保存')
      onClose?.()
    } catch (e) {
      if (e?.errorFields) return
      message.error(e?.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={<span>评价管理设置 {shopName && <Tag style={{ marginLeft: 8 }}>{shopName}</Tag>}</span>}
      open={open}
      onCancel={onClose}
      onOk={handleSave}
      confirmLoading={saving}
      okText="保存"
      cancelText="取消"
      width={620}
      destroyOnClose
    >
      <Spin spinning={loading}>
        <Form form={form} layout="vertical" disabled={saving}>
          <Form.Item
            label="自动回复开关"
            name="auto_reply_enabled"
            valuePropName="checked"
            extra="开启后, 系统每 30 分钟扫描新评价, 满足下方『评分下限』的评价 AI 自动起草并发送 (5 分钟后再发, 给你时间介入)."
          >
            <Switch checkedChildren="开" unCheckedChildren="关" />
          </Form.Item>

          <Form.Item
            label="自动回复评分下限"
            name="auto_reply_rating_floor"
            extra="只有 ≥ 此星级的评价会被自动回复. 默认 4 即 4-5 星自动, 1-3 星永远等你人工处理."
          >
            <Slider
              min={1} max={5} step={1}
              marks={{ 1: '1★', 2: '2★', 3: '3★', 4: '4★ (推荐)', 5: '5★' }}
            />
          </Form.Item>

          <Divider style={{ margin: '12px 0' }} />

          <Form.Item
            label="回复语气"
            name="reply_tone"
          >
            <Select>
              {TONE_OPTIONS.map(t => (
                <Select.Option key={t.value} value={t.value}>
                  <div>
                    <div>{t.label}</div>
                    <Text type="secondary" style={{ fontSize: 11 }}>{t.desc}</Text>
                  </div>
                </Select.Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item
            label="品牌签名 (可选)"
            name="brand_signature"
            extra="拼在每条回复结尾, 例如 'С любовью, Sharino' / 'Команда BabyBox'. 留空则 AI 自由发挥."
          >
            <Input placeholder="例: С любовью, Sharino" maxLength={200} showCount />
          </Form.Item>

          <Form.Item
            label="自定义 prompt 补充 (高级)"
            name="custom_prompt_extra"
            extra="给 AI 的额外指令, 例如 '我们品牌强调环保, 多提天然材质' / '每次提一下 30 天无理由退换'. 仅高级用户使用."
          >
            <TextArea
              rows={3}
              maxLength={1000} showCount
              placeholder="(可选) 给 AI 的额外指令..."
            />
          </Form.Item>
        </Form>

        <Paragraph type="secondary" style={{ fontSize: 11, marginBottom: 0, marginTop: 8 }}>
          💡 注: 所有设置仅作用于当前店铺. 不同店铺可独立配置不同语气/签名.
        </Paragraph>
      </Spin>
    </Modal>
  )
}

export default SettingsModal
