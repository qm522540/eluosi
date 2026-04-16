import { useState, useEffect, useRef } from 'react'
import {
  Button, Modal, Form, Select, Switch, message, Alert, Spin, Typography, Space, Tag,
} from 'antd'
import { CloudDownloadOutlined, LoadingOutlined } from '@ant-design/icons'
import { getShops } from '@/api/shops'
import { initFromWB } from '@/api/mapping'

const { Text, Paragraph } = Typography

const TIPS = [
  '正在从商品数据反查 WB 店铺已用到的分类...',
  '正在拉取 WB 全量分类字典...',
  '正在调用 AI 翻译俄文分类名...',
  '正在拉取 charcs 属性列表并翻译...',
  '正在建立本地分类 ↔ WB 映射...',
]

const InitFromWBButton = ({ onSuccess }) => {
  const [open, setOpen] = useState(false)
  const [shops, setShops] = useState([])
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [tipIndex, setTipIndex] = useState(0)
  const [result, setResult] = useState(null)
  const timerRef = useRef(null)

  useEffect(() => {
    if (!open) return
    getShops({ page: 1, page_size: 100 })
      .then((res) => setShops(res.data?.items || []))
      .catch(() => setShops([]))
  }, [open])

  // Loading 期间文案轮播，每 8 秒切一条
  useEffect(() => {
    if (loading) {
      setTipIndex(0)
      timerRef.current = setInterval(() => {
        setTipIndex((i) => (i + 1) % TIPS.length)
      }, 8000)
    } else if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [loading])

  const wbShopOptions = shops
    .filter((s) => s.platform === 'wb')
    .map((s) => ({ label: s.name, value: s.id }))

  const openDialog = () => {
    form.resetFields()
    form.setFieldsValue({ include_enum_values: true })
    setResult(null)
    setOpen(true)
  }

  const closeDialog = () => {
    if (loading) return
    setOpen(false)
    setResult(null)
  }

  const submit = async () => {
    const values = await form.validateFields()
    Modal.confirm({
      title: '确认从 WB 初始化？',
      content: '这将从 WB 店铺拉取分类和属性，预计 30-120 秒。期间不可关闭。',
      okText: '开始',
      cancelText: '再想想',
      onOk: () => doInit(values),
    })
  }

  const doInit = async (values) => {
    setLoading(true)
    setResult(null)
    try {
      const res = await initFromWB({
        shop_id: values.shop_id,
        include_enum_values: !!values.include_enum_values,
      })
      const data = res.data || {}
      setResult(data)
      message.success(
        `WB 初始化完成：分类 ${data.categories ?? 0} / 属性 ${data.attributes ?? 0} / 枚举值 ${data.values ?? 0}`,
        6,
      )
      onSuccess?.()
    } catch (err) {
      message.error(err.message || 'WB 初始化失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <Button type="primary" icon={<CloudDownloadOutlined />} onClick={openDialog}>
        从 WB 初始化
      </Button>
      <Modal
        open={open}
        title="从 WB 店铺一键初始化映射"
        okText={loading ? 'AI 处理中...' : (result ? '关闭' : '开始初始化')}
        cancelButtonProps={{ disabled: loading, style: result ? { display: 'none' } : {} }}
        okButtonProps={{
          loading,
          icon: result ? undefined : <CloudDownloadOutlined />,
          type: result ? 'default' : 'primary',
        }}
        onOk={result ? closeDialog : submit}
        onCancel={closeDialog}
        closable={!loading}
        maskClosable={!loading}
        destroyOnClose
        width={600}
      >
        <Spin
          spinning={loading}
          indicator={<LoadingOutlined spin />}
          tip={TIPS[tipIndex]}
        >
          {result ? (
            <div>
              <Alert
                type="success"
                showIcon
                message="初始化完成"
                style={{ marginBottom: 12 }}
                description={
                  <Space wrap>
                    <Tag color="geekblue">新建分类 {result.categories ?? 0}</Tag>
                    <Tag color="purple">新建属性 {result.attributes ?? 0}</Tag>
                    <Tag color="green">枚举值 {result.values ?? 0}</Tag>
                  </Space>
                }
              />
              {result.skipped && result.skipped.length > 0 && (
                <Alert
                  type="warning"
                  showIcon
                  message={`跳过 ${result.skipped.length} 项`}
                  description={
                    <ul style={{ margin: 0, paddingLeft: 18, maxHeight: 200, overflow: 'auto' }}>
                      {result.skipped.map((s, i) => (
                        <li key={i}><Text type="secondary" style={{ fontSize: 12 }}>{s}</Text></li>
                      ))}
                    </ul>
                  }
                />
              )}
            </div>
          ) : (
            <>
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 12 }}
                message="一键初始化：WB 店铺已用到的分类 → 本地分类 + WB 映射"
                description={
                  <Paragraph style={{ marginBottom: 0, fontSize: 13 }}>
                    1. 从商品反查店铺用到的 WB subjectID 集合<br />
                    2. 拉 WB 分类字典并批量 AI 翻译俄文 → 中文<br />
                    3. 建本地分类 + WB 映射（自动确认 is_confirmed=1）<br />
                    4. 拉 charcs 属性并翻译，可选包含枚举值
                  </Paragraph>
                }
              />
              <Form form={form} layout="vertical" disabled={loading}>
                <Form.Item
                  name="shop_id"
                  label="WB 店铺"
                  rules={[{ required: true, message: '请选择 WB 店铺' }]}
                  extra={wbShopOptions.length === 0 ? '未配置 WB 店铺' : '需已同步过商品，platform_listings 要有数据'}
                >
                  <Select
                    showSearch
                    placeholder="选择 WB 店铺"
                    options={wbShopOptions}
                    optionFilterProp="label"
                    notFoundContent="无 WB 店铺"
                  />
                </Form.Item>
                <Form.Item
                  name="include_enum_values"
                  label="是否包含枚举值翻译"
                  valuePropName="checked"
                  extra="勾选会多拉一次 dictionary 并翻译，耗时更长但一次到位"
                >
                  <Switch checkedChildren="包含" unCheckedChildren="跳过" />
                </Form.Item>
              </Form>
            </>
          )}
        </Spin>
      </Modal>
    </>
  )
}

export default InitFromWBButton
