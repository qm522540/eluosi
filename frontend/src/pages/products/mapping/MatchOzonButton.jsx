import { useState, useEffect, useRef } from 'react'
import {
  Button, Modal, Form, Select, message, Alert, Spin, Typography, Space, Tag, Tooltip,
} from 'antd'
import { ThunderboltOutlined, LoadingOutlined } from '@ant-design/icons'
import { getShops } from '@/api/shops'
import { matchOzon } from '@/api/mapping'

const { Text, Paragraph } = Typography

const TIPS = [
  '正在遍历本地分类...',
  '正在调用 AI 匹配 Ozon 分类...',
  '正在为每个分类批量生成 Ozon 属性映射...',
  '正在 upsert 映射数据到数据库...',
]

const MatchOzonButton = ({ localCategoryCount = 0, onSuccess }) => {
  const [open, setOpen] = useState(false)
  const [shops, setShops] = useState([])
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [tipIndex, setTipIndex] = useState(0)
  const [result, setResult] = useState(null)
  const timerRef = useRef(null)

  const canUse = localCategoryCount > 0

  useEffect(() => {
    if (!open) return
    getShops({ page: 1, page_size: 100 })
      .then((res) => setShops(res.data?.items || []))
      .catch(() => setShops([]))
  }, [open])

  useEffect(() => {
    if (loading) {
      setTipIndex(0)
      timerRef.current = setInterval(() => {
        setTipIndex((i) => (i + 1) % TIPS.length)
      }, 10000)
    } else if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [loading])

  const ozonShopOptions = shops
    .filter((s) => s.platform === 'ozon')
    .map((s) => ({ label: s.name, value: s.id }))

  const openDialog = () => {
    if (!canUse) {
      message.warning('请先创建本地分类（或点"从 WB 初始化"）')
      return
    }
    form.resetFields()
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
      title: `确认对 ${localCategoryCount} 个本地分类批量匹配 Ozon？`,
      content: `每个分类约 5-15 秒，总耗时 60-300 秒。期间不可关闭。所有生成的映射都标为"AI 推荐·待确认"。`,
      okText: '开始匹配',
      cancelText: '再想想',
      onOk: () => doMatch(values),
    })
  }

  const doMatch = async (values) => {
    setLoading(true)
    setResult(null)
    try {
      const res = await matchOzon({ shop_id: values.shop_id })
      const data = res.data || {}
      setResult(data)
      const cats = data.categories || {}
      const attrs = data.attributes || {}
      message.success(
        `Ozon 匹配完成：分类 ${cats.matched ?? 0}/${(cats.matched ?? 0) + (cats.failed ?? 0)}，属性 ${attrs.matched ?? 0}/${(attrs.matched ?? 0) + (attrs.failed ?? 0)}`,
        8,
      )
      onSuccess?.()
    } catch (err) {
      message.error(err.message || 'Ozon 匹配失败')
    } finally {
      setLoading(false)
    }
  }

  const btn = (
    <Button
      icon={<ThunderboltOutlined />}
      onClick={openDialog}
      disabled={!canUse}
    >
      AI 匹配 Ozon
    </Button>
  )

  return (
    <>
      {canUse ? btn : <Tooltip title={'请先创建本地分类（或点"从 WB 初始化"）'}>{btn}</Tooltip>}
      <Modal
        open={open}
        title="AI 批量匹配 Ozon 映射"
        okText={loading ? 'AI 处理中...' : (result ? '关闭' : '开始匹配')}
        cancelButtonProps={{ disabled: loading, style: result ? { display: 'none' } : {} }}
        okButtonProps={{
          loading,
          icon: result ? undefined : <ThunderboltOutlined />,
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
                message="批量匹配完成"
                style={{ marginBottom: 12 }}
                description={
                  <Space direction="vertical" size={4}>
                    <Space wrap>
                      <Text type="secondary">品类映射：</Text>
                      <Tag color="green">成功 {result.categories?.matched ?? 0}</Tag>
                      <Tag color="red">失败 {result.categories?.failed ?? 0}</Tag>
                    </Space>
                    <Space wrap>
                      <Text type="secondary">属性映射：</Text>
                      <Tag color="green">成功 {result.attributes?.matched ?? 0}</Tag>
                      <Tag color="red">失败 {result.attributes?.failed ?? 0}</Tag>
                    </Space>
                  </Space>
                }
              />
              <Alert
                type="info"
                showIcon
                message={'所有新映射均为"AI 推荐·待确认"状态，请在品类/属性 Tab 逐条核对'}
              />
            </div>
          ) : (
            <>
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 12 }}
                message={
                  <span>
                    将对 <Text strong>{localCategoryCount}</Text> 个本地分类批量生成 Ozon 映射
                  </span>
                }
                description={
                  <Paragraph style={{ marginBottom: 0, fontSize: 13 }}>
                    1. 对每个本地分类调 AI 推荐 Ozon 分类映射<br />
                    2. 成功匹配的分类再批量推荐 Ozon 属性映射<br />
                    3. 所有新建映射均为 <Text strong>待确认</Text> 状态（is_confirmed=0）<br />
                    4. 需在品类/属性 Tab 逐条人工确认后才生效
                  </Paragraph>
                }
              />
              <Form form={form} layout="vertical" disabled={loading}>
                <Form.Item
                  name="shop_id"
                  label="Ozon 店铺"
                  rules={[{ required: true, message: '请选择 Ozon 店铺' }]}
                  extra={ozonShopOptions.length === 0 ? '未配置 Ozon 店铺' : '使用该店铺凭证调 Ozon 分类 API'}
                >
                  <Select
                    showSearch
                    placeholder="选择 Ozon 店铺"
                    options={ozonShopOptions}
                    optionFilterProp="label"
                    notFoundContent="无 Ozon 店铺"
                  />
                </Form.Item>
              </Form>
            </>
          )}
        </Spin>
      </Modal>
    </>
  )
}

export default MatchOzonButton
