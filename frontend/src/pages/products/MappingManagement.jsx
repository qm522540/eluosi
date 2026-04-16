import { useState, useEffect, useCallback } from 'react'
import { Typography, Card, Tree, Tabs, Empty, Spin, message, Row, Col } from 'antd'
import { PartitionOutlined } from '@ant-design/icons'
import { getLocalCategoryTree } from '@/api/mapping'

const { Title, Paragraph, Text } = Typography

// 把 §3.2 后端树结构转成 Antd Tree 需要的格式
const toTreeData = (nodes) =>
  (nodes || []).map((n) => ({
    key: String(n.id),
    title: n.name_ru ? `${n.name} · ${n.name_ru}` : n.name,
    raw: n,
    children: n.children && n.children.length ? toTreeData(n.children) : undefined,
  }))

const MappingManagement = () => {
  const [treeData, setTreeData] = useState([])
  const [treeLoading, setTreeLoading] = useState(false)
  const [selectedKey, setSelectedKey] = useState(null)
  const [selectedNode, setSelectedNode] = useState(null)
  const [activeTab, setActiveTab] = useState('category')

  const loadTree = useCallback(async () => {
    setTreeLoading(true)
    try {
      const res = await getLocalCategoryTree()
      setTreeData(toTreeData(res.data?.tree))
    } catch (err) {
      message.error(err.message || '加载本地分类树失败')
    } finally {
      setTreeLoading(false)
    }
  }, [])

  useEffect(() => {
    loadTree()
  }, [loadTree])

  const onTreeSelect = (keys, { node }) => {
    if (!keys.length) {
      setSelectedKey(null)
      setSelectedNode(null)
      return
    }
    setSelectedKey(keys[0])
    setSelectedNode(node.raw)
  }

  const renderTabContent = () => {
    if (!selectedNode) {
      return <Empty description="请先在左侧选择一个本地分类" />
    }
    return (
      <Card size="small" bordered>
        <Text type="secondary">
          当前选中：<Text strong>{selectedNode.name}</Text>
          {selectedNode.name_ru && <Text type="secondary"> · {selectedNode.name_ru}</Text>}
        </Text>
        <Paragraph style={{ marginTop: 12, marginBottom: 0 }} type="secondary">
          {activeTab === 'category' && '品类映射 Tab 待填充（Task 5）'}
          {activeTab === 'attribute' && '属性映射 Tab 待填充（Task 7）'}
          {activeTab === 'value' && '属性值映射 Tab 待填充（Task 8）'}
        </Paragraph>
      </Card>
    )
  }

  return (
    <div>
      <Title level={3}>
        <PartitionOutlined /> 映射管理
      </Title>
      <Paragraph type="secondary">
        本地统一分类 → WB / Ozon 分类 / 属性 / 属性值 映射。AI 推荐 + 人工确认流程见
        <Text code>docs/api/category_mapping.md</Text>
      </Paragraph>

      <Row gutter={16}>
        <Col xs={24} md={8} lg={7} xl={6}>
          <Card
            title="本地分类"
            size="small"
            styles={{ body: { padding: 8, minHeight: 400 } }}
          >
            <Spin spinning={treeLoading}>
              {treeData.length === 0 && !treeLoading ? (
                <Empty description="暂无本地分类" />
              ) : (
                <Tree
                  blockNode
                  showLine
                  treeData={treeData}
                  selectedKeys={selectedKey ? [selectedKey] : []}
                  onSelect={onTreeSelect}
                />
              )}
            </Spin>
          </Card>
        </Col>
        <Col xs={24} md={16} lg={17} xl={18}>
          <Card size="small">
            <Tabs
              activeKey={activeTab}
              onChange={setActiveTab}
              items={[
                { key: 'category', label: '品类映射' },
                { key: 'attribute', label: '属性映射' },
                { key: 'value', label: '属性值映射' },
              ]}
            />
            {renderTabContent()}
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default MappingManagement
