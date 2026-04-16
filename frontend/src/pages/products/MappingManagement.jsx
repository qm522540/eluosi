import { Typography, Card } from 'antd'

const { Title, Paragraph } = Typography

const MappingManagement = () => {
  return (
    <div>
      <Title level={3}>映射管理</Title>
      <Paragraph type="secondary">
        本地统一分类 → 各平台分类/属性/属性值 映射管理。骨架中，详见 docs/api/category_mapping.md
      </Paragraph>
      <Card>页面建设中...</Card>
    </div>
  )
}

export default MappingManagement
