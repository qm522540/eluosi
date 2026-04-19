import { Typography, Alert } from 'antd'

const { Title, Paragraph } = Typography

const Optimize = () => (
  <div>
    <Title level={4}>优化建议（付费词反哺自然词）</Title>
    <Alert
      type="info"
      showIcon
      message="骨架已就位，页面内容 Step 5 填充"
      description="接口已通 /api/v1/seo/shop/{shop_id}/candidates 等 4 个。"
    />
    <Paragraph type="secondary" style={{ marginTop: 12 }}>
      即将渲染：顶部过滤条 + 4 格统计 + 候选词表格（多源徽章 / 覆盖情况 / 操作按钮）。
    </Paragraph>
  </div>
)

export default Optimize
