import { Typography, Alert } from 'antd'

const { Title } = Typography

const Tracking = () => (
  <div>
    <Title level={4}>排名追踪</Title>
    <Alert type="warning" showIcon
      message="四期功能"
      description="核心词每日自动查商品搜索排名 + 下滑预警。" />
  </div>
)

export default Tracking
