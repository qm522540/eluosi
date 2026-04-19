import { Typography, Alert } from 'antd'

const { Title } = Typography

const Health = () => (
  <div>
    <Title level={4}>健康诊断</Title>
    <Alert type="warning" showIcon
      message="二期功能"
      description="每个商品 0-100 分 SEO 健康分（关键词覆盖 + 属性填充 + 评分销量 + 价格竞争力）。" />
  </div>
)

export default Health
