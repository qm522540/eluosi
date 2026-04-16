import { useState, useEffect } from 'react'
import {
  Button, Modal, Form, Radio, Select, message, Alert, Spin, Typography, Tooltip,
} from 'antd'
import { ThunderboltOutlined, LoadingOutlined } from '@ant-design/icons'
import { getShops } from '@/api/shops'
import { aiSuggestAttributes, listCategoryMappings } from '@/api/mapping'

const { Text } = Typography

const AISuggestAttributesButton = ({ localCategoryId, localCategoryName, onSuccess }) => {
  const [open, setOpen] = useState(false)
  const [shops, setShops] = useState([])
  const [mappedPlatforms, setMappedPlatforms] = useState({ wb: false, ozon: false })
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [checkingPre, setCheckingPre] = useState(false)

  useEffect(() => {
    if (!open) return
    getShops({ page: 1, page_size: 100 })
      .then((res) => setShops(res.data?.items || []))
      .catch(() => setShops([]))
    setCheckingPre(true)
    listCategoryMappings({ local_category_id: localCategoryId })
      .then((res) => {
        const items = res.data?.items || []
        const next = { wb: false, ozon: false }
        items.forEach((m) => {
          if (m.platform in next) next[m.platform] = true
        })
        setMappedPlatforms(next)
        const firstMapped = Object.entries(next).find(([, v]) => v)?.[0]
        if (firstMapped) form.setFieldsValue({ platform: firstMapped })
      })
      .catch(() => setMappedPlatforms({ wb: false, ozon: false }))
      .finally(() => setCheckingPre(false))
  }, [open, localCategoryId, form])

  const openDialog = () => {
    form.resetFields()
    setOpen(true)
  }

  const closeDialog = () => {
    if (loading) return
    setOpen(false)
  }

  const submit = async () => {
    const values = await form.validateFields()
    if (!mappedPlatforms[values.platform]) {
      message.error('该平台尚未完成品类映射，请先去"品类映射"Tab 添加')
      return
    }
    setLoading(true)
    try {
      const res = await aiSuggestAttributes({
        local_category_id: localCategoryId,
        platform: values.platform,
        shop_id: values.shop_id,
      })
      const count = res.data?.count ?? 0
      message.success(`AI 推荐完成，写入 ${count} 条属性映射`, 5)
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

  const noMappingAtAll = !mappedPlatforms.wb && !mappedPlatforms.ozon

  return (
    <>
      <Button size="small" type="primary" icon={<ThunderboltOutlined />} onClick={openDialog}>
        AI 推荐属性
      </Button>
      <Modal
        open={open}
        title="AI 推荐属性映射"
        okText={loading ? 'AI 分析中...' : '开始推荐'}
        cancelButtonProps={{ disabled: loading }}
        okButtonProps={{
          loading,
          icon: <ThunderboltOutlined />,
          disabled: checkingPre || noMappingAtAll,
        }}
        onOk={submit}
        onCancel={closeDialog}
        closable={!loading}
        maskClosable={!loading}
        destroyOnClose
      >
        <Spin
          spinning={loading}
          indicator={<LoadingOutlined spin />}
          tip="AI 正在比对平台属性清单，通常 5-15 秒..."
        >
          {noMappingAtAll && !checkingPre ? (
            <Alert
              type="warning"
              showIcon
              message="请先完成品类映射"
              description={`本地分类"${localCategoryName}"尚未在任何平台上有品类映射。请先到"品类映射"Tab 完成映射（可用 AI 推荐），再来推荐属性。`}
            />
          ) : (
            <>
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 12 }}
                message={<span>为 <Text strong>{localCategoryName}</Text> 的选定平台批量生成属性映射</span>}
                description="AI 会拉取平台该分类下所有属性清单，自动给每个属性生成中文名并写入映射表。"
              />
              <Form form={form} layout="vertical" disabled={loading}>
                <Form.Item
                  name="platform"
                  label="推荐目标平台"
                  rules={[{ required: true }]}
                >
                  <Radio.Group>
                    <Tooltip title={mappedPlatforms.wb ? '' : '该平台尚无品类映射'}>
                      <Radio value="wb" disabled={!mappedPlatforms.wb}>Wildberries</Radio>
                    </Tooltip>
                    <Tooltip title={mappedPlatforms.ozon ? '' : '该平台尚无品类映射'}>
                      <Radio value="ozon" disabled={!mappedPlatforms.ozon}>Ozon</Radio>
                    </Tooltip>
                  </Radio.Group>
                </Form.Item>
                <Form.Item
                  name="shop_id"
                  label="使用哪个店铺的凭证调用平台 API"
                  rules={[{ required: true, message: '请选择店铺' }]}
                >
                  <Select showSearch placeholder="选择店铺" options={shopOptions} optionFilterProp="label" />
                </Form.Item>
              </Form>
            </>
          )}
        </Spin>
      </Modal>
    </>
  )
}

export default AISuggestAttributesButton
