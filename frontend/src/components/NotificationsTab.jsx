import { useState, useEffect, useCallback } from 'react'
import { Table, Button, Tag, Space, Badge, Tooltip, Select, message, Empty } from 'antd'
import {
  BellOutlined, CheckOutlined, ReloadOutlined,
  WarningOutlined, BarChartOutlined, AlertOutlined,
  RobotOutlined, InboxOutlined, DesktopOutlined,
} from '@ant-design/icons'
import { getNotifications, markNotificationRead } from '@/api/notifications'

const typeConfig = {
  roi_alert: { label: 'ROI告警', color: 'red', icon: <AlertOutlined /> },
  task_failure: { label: '任务失败', color: 'orange', icon: <WarningOutlined /> },
  ai_decision: { label: 'AI决策', color: 'purple', icon: <RobotOutlined /> },
  daily_report: { label: '日报', color: 'blue', icon: <BarChartOutlined /> },
  stock_alert: { label: '库存预警', color: 'gold', icon: <InboxOutlined /> },
  system: { label: '系统通知', color: 'default', icon: <DesktopOutlined /> },
}

const NotificationsTab = () => {
  const [notifications, setNotifications] = useState([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [filter, setFilter] = useState(null)

  const fetchNotifications = useCallback(async (p = page, readFilter = filter) => {
    setLoading(true)
    try {
      const params = { page: p, page_size: 15 }
      if (readFilter !== null) {
        params.is_read = readFilter
      }
      const res = await getNotifications(params)
      setNotifications(res.data.items)
      setTotal(res.data.total)
    } catch (err) {
      message.error('获取通知列表失败')
    } finally {
      setLoading(false)
    }
  }, [page, filter])

  useEffect(() => {
    fetchNotifications()
  }, [fetchNotifications])

  const handleMarkRead = async (id) => {
    try {
      await markNotificationRead(id)
      message.success('已标记为已读')
      fetchNotifications()
    } catch (err) {
      message.error('操作失败')
    }
  }

  const handleFilterChange = (value) => {
    setFilter(value)
    setPage(1)
    fetchNotifications(1, value)
  }

  const columns = [
    {
      title: '状态',
      key: 'is_read',
      width: 60,
      render: (_, record) => (
        record.is_read
          ? <Badge status="default" />
          : <Badge status="processing" />
      ),
    },
    {
      title: '类型',
      dataIndex: 'notification_type',
      key: 'type',
      width: 120,
      render: (type) => {
        const config = typeConfig[type] || { label: type, color: 'default', icon: <BellOutlined /> }
        return (
          <Tag icon={config.icon} color={config.color}>
            {config.label}
          </Tag>
        )
      },
    },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      render: (text, record) => (
        <span style={{ fontWeight: record.is_read ? 'normal' : 600 }}>
          {text}
        </span>
      ),
    },
    {
      title: '内容',
      dataIndex: 'content',
      key: 'content',
      ellipsis: true,
      render: (text) => (
        <Tooltip title={text}>
          <span style={{ color: '#666' }}>{text}</span>
        </Tooltip>
      ),
    },
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (v) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_, record) => (
        record.is_read ? (
          <span style={{ color: '#ccc' }}>已读</span>
        ) : (
          <Button
            type="link"
            size="small"
            icon={<CheckOutlined />}
            onClick={() => handleMarkRead(record.id)}
          >
            标为已读
          </Button>
        )
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Space>
          <span style={{ color: '#666' }}>系统通知与告警消息</span>
          <Select
            placeholder="筛选状态"
            allowClear
            style={{ width: 120 }}
            value={filter}
            onChange={handleFilterChange}
            options={[
              { value: 0, label: '未读' },
              { value: 1, label: '已读' },
            ]}
          />
        </Space>
        <Button icon={<ReloadOutlined />} onClick={() => fetchNotifications()}>刷新</Button>
      </div>

      <Table
        columns={columns}
        dataSource={notifications}
        rowKey="id"
        loading={loading}
        locale={{
          emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无通知" />,
        }}
        pagination={{
          current: page,
          total,
          pageSize: 15,
          showTotal: (t) => `共 ${t} 条通知`,
          onChange: (p) => { setPage(p); fetchNotifications(p) },
        }}
        rowClassName={(record) => record.is_read ? '' : 'ant-table-row-selected'}
      />
    </div>
  )
}

export default NotificationsTab
