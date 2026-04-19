import { Typography, Alert } from 'antd'

const { Title } = Typography

const Report = () => (
  <div>
    <Title level={4}>效果报表</Title>
    <Alert type="warning" showIcon
      message="六期功能"
      description="改标题前后 7/14/30 天的曝光 / 订单 / ROAS 对比 + 月度 ROI 汇总 + Excel 导出。" />
  </div>
)

export default Report
