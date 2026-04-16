import { useState, useEffect, useCallback } from 'react'
import {
  Typography, Card, Tree, Tabs, Empty, Spin, message, Row, Col, Button, Space,
  Modal, Form, Input, Popconfirm, Tooltip,
} from 'antd'
import {
  PartitionOutlined, PlusOutlined, EditOutlined, DeleteOutlined, ReloadOutlined,
} from '@ant-design/icons'
import {
  getLocalCategoryTree,
  createLocalCategory,
  updateLocalCategory,
  deleteLocalCategory,
} from '@/api/mapping'
import CategoryMappingTab from './mapping/CategoryMappingTab'
import AISuggestCategoryButton from './mapping/AISuggestCategoryButton'
import AttributeMappingTab from './mapping/AttributeMappingTab'
import AISuggestAttributesButton from './mapping/AISuggestAttributesButton'
import AttributeValueMappingDrawer from './mapping/AttributeValueMappingDrawer'

const { Title, Paragraph, Text } = Typography

const MAX_LEVEL = 3

// CategoryMappingTab + AI 推荐按钮组合：按钮塞到 aiSlot，通过 refreshKey 让表格刷新
const CategoryMappingTabWithAI = ({ localCategoryId, localCategoryName }) => {
  const [refreshKey, setRefreshKey] = useState(0)
  return (
    <CategoryMappingTab
      key={`${localCategoryId}-${refreshKey}`}
      localCategoryId={localCategoryId}
      localCategoryName={localCategoryName}
      aiSlot={
        <AISuggestCategoryButton
          localCategoryId={localCategoryId}
          localCategoryName={localCategoryName}
          onSuccess={() => setRefreshKey((k) => k + 1)}
        />
      }
    />
  )
}

const AttributeMappingTabWithAI = ({ localCategoryId, localCategoryName, onManageValues }) => {
  const [refreshKey, setRefreshKey] = useState(0)
  return (
    <AttributeMappingTab
      key={`${localCategoryId}-${refreshKey}`}
      localCategoryId={localCategoryId}
      localCategoryName={localCategoryName}
      onManageValues={onManageValues}
      aiSlot={
        <AISuggestAttributesButton
          localCategoryId={localCategoryId}
          localCategoryName={localCategoryName}
          onSuccess={() => setRefreshKey((k) => k + 1)}
        />
      }
    />
  )
}

const toTreeData = (nodes) =>
  (nodes || []).map((n) => ({
    key: String(n.id),
    title: n.name_ru ? `${n.name} · ${n.name_ru}` : n.name,
    raw: n,
    children: n.children && n.children.length ? toTreeData(n.children) : undefined,
  }))

// 从 key 递归找节点
const findNode = (nodes, key) => {
  for (const n of nodes || []) {
    if (n.key === key) return n
    if (n.children) {
      const hit = findNode(n.children, key)
      if (hit) return hit
    }
  }
  return null
}

// 收集全部 key，用于 expandAll
const collectKeys = (nodes) => {
  const out = []
  const walk = (arr) => {
    for (const n of arr || []) {
      out.push(n.key)
      if (n.children) walk(n.children)
    }
  }
  walk(nodes)
  return out
}

const MappingManagement = () => {
  const [treeData, setTreeData] = useState([])
  const [treeLoading, setTreeLoading] = useState(false)
  const [expandedKeys, setExpandedKeys] = useState([])
  const [selectedKey, setSelectedKey] = useState(null)
  const [selectedNode, setSelectedNode] = useState(null)
  const [activeTab, setActiveTab] = useState('category')

  // 编辑态：{ mode: 'create_root' | 'create_child' | 'rename', target }
  const [editing, setEditing] = useState(null)
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)

  // 属性值映射 Drawer 当前打开的属性映射
  const [valueDrawerAttr, setValueDrawerAttr] = useState(null)

  const loadTree = useCallback(async (keepSelectedKey) => {
    setTreeLoading(true)
    try {
      const res = await getLocalCategoryTree()
      const next = toTreeData(res.data?.tree)
      setTreeData(next)
      setExpandedKeys((prev) => (prev.length ? prev : collectKeys(next)))
      // 同步选中节点的最新数据
      if (keepSelectedKey) {
        const hit = findNode(next, keepSelectedKey)
        setSelectedNode(hit?.raw ?? null)
        if (!hit) setSelectedKey(null)
      }
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

  const openCreate = (mode) => {
    setEditing({ mode })
    form.resetFields()
  }

  const openRename = () => {
    if (!selectedNode) return
    setEditing({ mode: 'rename', target: selectedNode })
    form.setFieldsValue({ name: selectedNode.name, name_ru: selectedNode.name_ru || '' })
  }

  const closeEdit = () => {
    setEditing(null)
    form.resetFields()
  }

  const submitEdit = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      if (editing.mode === 'create_root') {
        const res = await createLocalCategory({
          name: values.name,
          name_ru: values.name_ru || null,
          parent_id: null,
        })
        message.success('创建成功')
        closeEdit()
        await loadTree()
        const newId = res.data?.id ? String(res.data.id) : null
        if (newId) setSelectedKey(newId)
      } else if (editing.mode === 'create_child') {
        await createLocalCategory({
          name: values.name,
          name_ru: values.name_ru || null,
          parent_id: selectedNode.id,
        })
        message.success('创建成功')
        closeEdit()
        await loadTree(selectedKey)
      } else if (editing.mode === 'rename') {
        await updateLocalCategory(editing.target.id, {
          name: values.name,
          name_ru: values.name_ru || null,
        })
        message.success('修改成功')
        closeEdit()
        await loadTree(selectedKey)
      }
    } catch (err) {
      if (err?.errorFields) return
      message.error(err.message || '操作失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!selectedNode) return
    try {
      await deleteLocalCategory(selectedNode.id)
      message.success('删除成功')
      setSelectedKey(null)
      setSelectedNode(null)
      await loadTree()
    } catch (err) {
      message.error(err.message || '删除失败')
    }
  }

  const canAddChild = selectedNode && (selectedNode.level ?? 1) < MAX_LEVEL

  const editModalTitle =
    editing?.mode === 'create_root' ? '新建顶级分类'
      : editing?.mode === 'create_child' ? `在 "${selectedNode?.name}" 下新建子分类`
      : editing?.mode === 'rename' ? `重命名 "${editing?.target?.name}"`
      : ''

  const renderTabContent = () => {
    if (!selectedNode) {
      return <Empty description="请先在左侧选择一个本地分类" />
    }
    if (activeTab === 'category') {
      return (
        <CategoryMappingTabWithAI
          key={selectedNode.id}
          localCategoryId={selectedNode.id}
          localCategoryName={selectedNode.name}
        />
      )
    }
    if (activeTab === 'attribute') {
      return (
        <AttributeMappingTabWithAI
          key={selectedNode.id}
          localCategoryId={selectedNode.id}
          localCategoryName={selectedNode.name}
          onManageValues={(row) => setValueDrawerAttr(row)}
        />
      )
    }
    return (
      <Card size="small" bordered>
        <Text type="secondary">
          当前选中：<Text strong>{selectedNode.name}</Text>
          {selectedNode.name_ru && <Text type="secondary"> · {selectedNode.name_ru}</Text>}
        </Text>
        <Paragraph style={{ marginTop: 12, marginBottom: 0 }} type="secondary">
          属性值映射按属性绑定，请切到 <Text strong>属性映射</Text> Tab，点 enum 类型属性行的
          <Text strong> 值映射 </Text> 按钮，从右侧抽屉管理。
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
            extra={
              <Space size={4}>
                <Tooltip title="刷新">
                  <Button
                    type="text"
                    size="small"
                    icon={<ReloadOutlined />}
                    onClick={() => loadTree(selectedKey)}
                  />
                </Tooltip>
                <Tooltip title="新建顶级分类">
                  <Button
                    type="text"
                    size="small"
                    icon={<PlusOutlined />}
                    onClick={() => openCreate('create_root')}
                  />
                </Tooltip>
              </Space>
            }
          >
            <Spin spinning={treeLoading}>
              {treeData.length === 0 && !treeLoading ? (
                <Empty description="暂无本地分类，点右上角 + 新建">
                  <Button type="primary" icon={<PlusOutlined />} onClick={() => openCreate('create_root')}>
                    新建顶级分类
                  </Button>
                </Empty>
              ) : (
                <Tree
                  blockNode
                  showLine
                  treeData={treeData}
                  expandedKeys={expandedKeys}
                  onExpand={setExpandedKeys}
                  selectedKeys={selectedKey ? [selectedKey] : []}
                  onSelect={onTreeSelect}
                />
              )}
            </Spin>

            {selectedNode && (
              <div style={{ padding: 8, borderTop: '1px solid #f0f0f0', marginTop: 8 }}>
                <Space wrap size={[4, 4]}>
                  <Tooltip title={canAddChild ? '' : '已到 3 级上限'}>
                    <Button
                      size="small"
                      icon={<PlusOutlined />}
                      disabled={!canAddChild}
                      onClick={() => openCreate('create_child')}
                    >
                      子分类
                    </Button>
                  </Tooltip>
                  <Button size="small" icon={<EditOutlined />} onClick={openRename}>
                    重命名
                  </Button>
                  <Popconfirm
                    title="删除此分类？"
                    description="有子分类将无法删除；会级联删除此分类下所有品类映射"
                    okText="删除"
                    okButtonProps={{ danger: true }}
                    cancelText="取消"
                    onConfirm={handleDelete}
                  >
                    <Button size="small" danger icon={<DeleteOutlined />}>
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
              </div>
            )}
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

      <AttributeValueMappingDrawer
        open={!!valueDrawerAttr}
        attributeMapping={valueDrawerAttr}
        onClose={() => setValueDrawerAttr(null)}
      />

      <Modal
        open={!!editing}
        title={editModalTitle}
        onCancel={closeEdit}
        onOk={submitEdit}
        confirmLoading={saving}
        destroyOnClose
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label="中文名"
            rules={[{ required: true, message: '中文名必填' }, { max: 100 }]}
          >
            <Input placeholder="如：项链" autoFocus />
          </Form.Item>
          <Form.Item
            name="name_ru"
            label="俄文名（可选，AI 推荐映射时会用到）"
            rules={[{ max: 200 }]}
          >
            <Input placeholder="如：Ожерелья" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default MappingManagement
