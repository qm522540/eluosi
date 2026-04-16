import { useState, useEffect, useRef } from 'react'
import {
  Button, Modal, Form, Select, Switch, message, Alert, Spin, Typography, Space, Tag,
} from 'antd'
import { DeploymentUnitOutlined, LoadingOutlined } from '@ant-design/icons'
import { getShops } from '@/api/shops'
import { initFromOzon, listCategoryMappings } from '@/api/mapping'

const { Text, Paragraph } = Typography

const TIPS = [
  '正在反查 Ozon 店铺已用到的分类 ID...',
  '正在从 Ozon 分类树拉完整名称 + 面包屑...',
  'AI 归一去重中：判断每个 Ozon 分类是否能合并到已有本地分类...',
  '正在为独有 Ozon 分类新建本地分类 + 翻译...',
  '正在拉属性清单并复用同名属性...',
  '正在翻译枚举值并写入...',
]

const InitFromOzonButton = ({ onSuccess }) => {
  const [open, setOpen] = useState(false)
  const [shops, setShops] = useState([])
  const [hasWB, setHasWB] = useState(null) // null=加载中, true/false
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
    // 预检 WB 是否已初始化：任意一条 WB 品类映射即视为已初始化
    setHasWB(null)
    listCategoryMappings({ platform: 'wb' })
      .then((res) => setHasWB((res.data?.items || []).length > 0))
      .catch(() => setHasWB(false))
  }, [open])

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

  const ozonShopOptions = shops
    .filter((s) => s.platform === 'ozon')
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
      title: '确认从 Ozon 扩充？',
      content: 'AI 归一去重 + 新建独有分类 + 拉属性和枚举值，预计 40-180 秒。期间不可关闭。',
      okText: '开始',
      cancelText: '再想想',
      onOk: () => doInit(values),
    })
  }

  const doInit = async (values) => {
    setLoading(true)
    setResult(null)
    try {
      const res = await initFromOzon({
        shop_id: values.shop_id,
        include_enum_values: !!values.include_enum_values,
      })
      const data = res.data || {}
      setResult(data)
      message.success(
        `Ozon 扩充完成：新建分类 ${data.categories_new ?? 0} / 合并 ${data.categories_merged ?? 0} / 新属性 ${data.attributes_new ?? 0} / 复用属性 ${data.attributes_reused ?? 0}`,
        8,
      )
      onSuccess?.()
    } catch (err) {
      message.error(err.message || 'Ozon 扩充失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <Button icon={<DeploymentUnitOutlined />} onClick={openDialog}>
        从 Ozon 扩充
      </Button>
      <Modal
        open={open}
        title="从 Ozon 店铺扩充本地分类"
        okText={loading ? 'AI 处理中...' : (result ? '关闭' : '开始扩充')}
        cancelButtonProps={{ disabled: loading, style: result ? { display: 'none' } : {} }}
        okButtonProps={{
          loading,
          icon: result ? undefined : <DeploymentUnitOutlined />,
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
                message="Ozon 扩充完成"
                style={{ marginBottom: 12 }}
                description={
                  <Space direction="vertical" size={6}>
                    <Space wrap>
                      <Text type="secondary">分类：</Text>
                      <Tag color="geekblue">新建 {result.categories_new ?? 0}</Tag>
                      <Tag color="cyan">合并到已有 {result.categories_merged ?? 0}</Tag>
                    </Space>
                    <Space wrap>
                      <Text type="secondary">属性：</Text>
                      <Tag color="purple">新建 {result.attributes_new ?? 0}</Tag>
                      <Tag color="blue">复用同名 {result.attributes_reused ?? 0}</Tag>
                    </Space>
                    <Space wrap>
                      <Text type="secondary">枚举值：</Text>
                      <Tag color="green">{result.values ?? 0}</Tag>
                    </Space>
                  </Space>
                }
              />
              {result.skipped && result.skipped.length > 0 && (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 12 }}
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
              <Alert
                type="info"
                showIcon
                message={'新合并的 Ozon 映射均为"AI 推荐·待确认"状态（橙色），请到品类映射 Tab 逐条核对；独有分类已直接确认。'}
              />
            </div>
          ) : (
            <>
              {hasWB === false && (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 12 }}
                  message="尚未从 WB 初始化"
                  description={'建议先点"从 WB 初始化"有种子分类，AI 才能智能合并 Ozon 的同义分类。不想先做也可以继续——Ozon 会直接作为新建本地分类。'}
                />
              )}
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 12 }}
                message="一键扩充：AI 归一去重 + 补齐 Ozon 独有分类"
                description={
                  <Paragraph style={{ marginBottom: 0, fontSize: 13 }}>
                    1. 反查 Ozon 店铺已用到的 description_category_id<br />
                    2. AI 一次性判断每个 Ozon 分类能否合并到已有本地分类<br />
                    3. 可合并的 → 建 Ozon 品类映射 <Text strong>待确认</Text>（is_confirmed=0）<br />
                    4. 独有的 → 新建本地分类 + Ozon 映射 <Text strong>自动确认</Text><br />
                    5. 拉属性清单：同名复用 WB 已有属性，新属性新建<br />
                    6. 可选翻译枚举值（每属性最多 200 条）
                  </Paragraph>
                }
              />
              <Form form={form} layout="vertical" disabled={loading}>
                <Form.Item
                  name="shop_id"
                  label="Ozon 店铺"
                  rules={[{ required: true, message: '请选择 Ozon 店铺' }]}
                  extra={ozonShopOptions.length === 0 ? '未配置 Ozon 店铺' : '需已同步过商品，platform_listings 要有 description_category_id'}
                >
                  <Select
                    showSearch
                    placeholder="选择 Ozon 店铺"
                    options={ozonShopOptions}
                    optionFilterProp="label"
                    notFoundContent="无 Ozon 店铺"
                  />
                </Form.Item>
                <Form.Item
                  name="include_enum_values"
                  label="是否包含枚举值翻译"
                  valuePropName="checked"
                  extra="勾选会多拉一次属性字典并翻译"
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

export default InitFromOzonButton
