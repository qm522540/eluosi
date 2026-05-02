import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Card, Table, Tag, Space, Select, Typography, Modal, Empty, message,
} from 'antd'
import * as cloneApi from '@/api/clone'

const { Title, Text } = Typography

const STATUS_COLOR = {
  success: 'success', partial: 'warning', failed: 'error', skipped: 'default',
}

const TYPE_LABEL = {
  scan: '扫描', review: '审核', publish: '上架', price_sync: '跟价',
}

const CloneLogs = () => {
  const [searchParams] = useSearchParams()
  const [taskId, setTaskId] = useState(searchParams.get('task_id') || null)
  const [logType, setLogType] = useState(null)
  const [status, setStatus] = useState(null)
  const [logs, setLogs] = useState([])
  const [tasks, setTasks] = useState([])
  const [loading, setLoading] = useState(false)
  const [detailLog, setDetailLog] = useState(null)

  const load = async () => {
    setLoading(true)
    try {
      const params = { page: 1, size: 50 }
      if (taskId) params.task_id = taskId
      if (logType) params.log_type = logType
      if (status) params.status = status
      const r = await cloneApi.listLogs(params)
      setLogs(r.data?.items || [])
    } catch (e) {
      message.error(e.message || '加载日志失败')
    } finally {
      setLoading(false)
    }
  }

  const loadTasks = async () => {
    try {
      const r = await cloneApi.listTasks({ size: 100 })
      setTasks(r.data?.items || [])
    } catch (_e) {
      // 静默失败 — 任务下拉过滤不可用不阻塞日志主功能
    }
  }

  useEffect(() => { loadTasks() }, [])
  useEffect(() => { load() }, [taskId, logType, status])

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    {
      title: '时间', dataIndex: 'created_at', width: 180,
      render: (v) => v ? new Date(v).toLocaleString() : '-',
    },
    {
      title: '任务', dataIndex: 'task_id', width: 80,
      render: (v) => v ? `#${v}` : '系统',
    },
    {
      title: '类型', dataIndex: 'log_type', width: 80,
      render: (v) => <Tag>{TYPE_LABEL[v] || v}</Tag>,
    },
    {
      title: '状态', dataIndex: 'status', width: 80,
      render: (v) => <Tag color={STATUS_COLOR[v] || 'default'}>{v}</Tag>,
    },
    { title: '行数', dataIndex: 'rows_affected', width: 70 },
    {
      title: '耗时', dataIndex: 'duration_ms', width: 90,
      render: (v) => v ? `${v} ms` : '-',
    },
    {
      title: '摘要',
      render: (_, log) => {
        if (log.error_msg) return <Text type="danger">{log.error_msg.slice(0, 80)}</Text>
        if (log.detail) {
          const d = log.detail
          if (log.log_type === 'scan') {
            return (
              <Space size={4} wrap>
                <Text type="secondary">扫:{d.found}</Text>
                <Text type="success">新:{d.new}</Text>
                <Text>跳已发:{d.skip_published || 0}</Text>
                <Text>跳已拒:{d.skip_rejected || 0}</Text>
                {d.skip_category_missing > 0 && <Tag color="warning">类目缺{d.skip_category_missing}</Tag>}
                {d.ai_rewrite_failed > 0 && <Tag color="warning">AI败{d.ai_rewrite_failed}</Tag>}
              </Space>
            )
          }
          if (log.log_type === 'review') {
            return <Text>{d.action} pending#{d.pending_id}</Text>
          }
          if (log.log_type === 'publish') {
            return d.target_platform_sku_id
              ? <Text code>{d.target_platform_sku_id}</Text>
              : <Text type="danger">{d.error_msg?.slice(0, 80)}</Text>
          }
          if (log.log_type === 'price_sync') {
            return <Text>{d.old_price} → {d.new_price} ₽</Text>
          }
          return JSON.stringify(d).slice(0, 80)
        }
        return '-'
      },
    },
    {
      title: '操作', width: 80, fixed: 'right',
      render: (_, log) => (
        <a onClick={() => setDetailLog(log)}>详情</a>
      ),
    },
  ]

  return (
    <div style={{ padding: 16 }}>
      <Card
        title={<Title level={4} style={{ margin: 0 }}>克隆日志</Title>}
        extra={
          <Space>
            <Select value={taskId} placeholder="按任务" allowClear
              style={{ width: 220 }} onChange={setTaskId}
              options={[
                { value: null, label: '全部任务' },
                ...tasks.map(t => ({
                  value: t.id,
                  label: `#${t.id} ${t.target_shop?.name} ← ${t.source_shop?.name}`,
                })),
              ]} />
            <Select value={logType} placeholder="类型" allowClear
              style={{ width: 120 }} onChange={setLogType}
              options={Object.entries(TYPE_LABEL).map(([k, v]) => ({ value: k, label: v }))} />
            <Select value={status} placeholder="状态" allowClear
              style={{ width: 120 }} onChange={setStatus}
              options={['success', 'partial', 'failed', 'skipped'].map(s => ({ value: s, label: s }))} />
          </Space>
        }
      >
        {logs.length === 0 && !loading ? (
          <Empty description="无日志" />
        ) : (
          <Table
            rowKey="id" dataSource={logs} columns={columns}
            loading={loading} scroll={{ x: 1100 }}
            pagination={{ pageSize: 20 }}
          />
        )}
      </Card>

      <Modal
        title={`日志详情 #${detailLog?.id}`}
        open={!!detailLog}
        onCancel={() => setDetailLog(null)}
        footer={null}
        width={800}
      >
        {detailLog && (
          <pre style={{
            background: '#f5f5f5', padding: 12, borderRadius: 4,
            maxHeight: 500, overflow: 'auto', fontSize: 12,
          }}>
            {JSON.stringify(detailLog.detail || {}, null, 2)}
          </pre>
        )}
      </Modal>
    </div>
  )
}

export default CloneLogs
