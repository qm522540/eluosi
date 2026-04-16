import { useState, useEffect } from 'react'
import { Button, Modal, Form, Checkbox, Select, message, Alert, Spin, Typography } from 'antd'
import { ThunderboltOutlined, LoadingOutlined } from '@ant-design/icons'
import { getShops } from '@/api/shops'
import { aiSuggestCategory } from '@/api/mapping'

const { Text } = Typography

const PLATFORM_OPTIONS = [
  { label: 'Wildberries', value: 'wb' },
  { label: 'Ozon', value: 'ozon' },
]

const AISuggestCategoryButton = ({ localCategoryId, localCategoryName, onSuccess }) => {
  const [open, setOpen] = useState(false)
  const [shops, setShops] = useState([])
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    getShops({ page: 1, page_size: 100 })
      .then((res) => setShops(res.data?.items || []))
      .catch(() => setShops([]))
  }, [open])

  const openDialog = () => {
    form.resetFields()
    form.setFieldsValue({ platforms: ['wb', 'ozon'] })
    setOpen(true)
  }

  const closeDialog = () => {
    if (loading) return
    setOpen(false)
  }

  const submit = async () => {
    const values = await form.validateFields()
    setLoading(true)
    try {
      const res = await aiSuggestCategory({
        local_category_id: localCategoryId,
        platforms: values.platforms,
        shop_id: values.shop_id,
      })
      const suggestions = res.data?.suggestions || []
      const ok = suggestions.filter((s) => !s.error)
      const fail = suggestions.filter((s) => s.error)
      if (ok.length) {
        message.success(
          `AI 推荐成功：${ok.map((s) => `${s.platform.toUpperCase()} ${s.confidence}%`).join(' · ')}`,
          5,
        )
      }
      if (fail.length) {
        message.warning(
          `部分平台失败：${fail.map((s) => `${s.platform.toUpperCase()} ${s.error}`).join('；')}`,
          8,
        )
      }
      if (!ok.length && !fail.length) {
        message.info('AI 未返回可用建议')
      }
      setOpen(false)
      onSuccess?.()
    } catch (err) {
      message.error(err.message || 'AI 推荐失败')
    } finally {
      setLoading(false)
    }
  }

  const shopOptions = shops.map((s) => ({
    label: `${(s.platform || '').toUpperCase()} · ${s.name}`,
    value: s.id,
  }))

  return (
    <>
      <Button
        size="small"
        type="primary"
        icon={<ThunderboltOutlined />}
        onClick={openDialog}
      >
        AI 推荐映射
      </Button>
      <Modal
        open={open}
        title="AI 推荐品类映射"
        okText={loading ? 'AI 分析中...' : '开始推荐'}
        cancelButtonProps={{ disabled: loading }}
        okButtonProps={{ loading, icon: <ThunderboltOutlined /> }}
        onOk={submit}
        onCancel={closeDialog}
        closable={!loading}
        maskClosable={!loading}
        destroyOnClose
      >
        <Spin
          spinning={loading}
          indicator={<LoadingOutlined spin />}
          tip="AI 正在调取平台分类并比对，通常 5-15 秒..."
        >
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message={
              <span>
                为本地分类 <Text strong>{localCategoryName}</Text> 推荐平台映射
              </span>
            }
            description={'AI 会调用该店铺的平台凭证拉取全量分类树并比对俄文名；结果会自动写入列表，状态为 AI 推荐 · 待确认。'}
          />
          <Form form={form} layout="vertical" disabled={loading}>
            <Form.Item
              name="platforms"
              label="推荐目标平台"
              rules={[{ required: true, message: '至少选一个平台' }]}
            >
              <Checkbox.Group options={PLATFORM_OPTIONS} />
            </Form.Item>
            <Form.Item
              name="shop_id"
              label="使用哪个店铺的凭证调用平台 API"
              rules={[{ required: true, message: '请选择店铺' }]}
              extra="需要该店铺已正确配置平台 API 凭证"
            >
              <Select
                showSearch
                placeholder="选择店铺"
                options={shopOptions}
                optionFilterProp="label"
              />
            </Form.Item>
          </Form>
        </Spin>
      </Modal>
    </>
  )
}

export default AISuggestCategoryButton
