import { useState, useEffect, useCallback } from 'react'
import {
  Card, Table, Tag, Switch, Button, Space, Select, Alert, Modal, Form, Input,
  InputNumber, message, Tooltip, Badge, Empty, Divider, Typography,
} from 'antd'
import {
  ReloadOutlined, ApiOutlined, CheckCircleFilled, CloseCircleFilled,
  ClockCircleOutlined, PauseCircleOutlined, ExclamationCircleOutlined,
  ShopOutlined, GlobalOutlined, ThunderboltOutlined, SyncOutlined,
} from '@ant-design/icons'
import { getShops } from '@/api/shops'
import {
  getShopDataSources, getSharedDataSources,
  patchShopApiSwitch, patchDataSource, triggerSyncDataSource,
} from '@/api/data_source'
import { formatMoscowTime } from '@/utils/time'
import { PLATFORMS } from '@/utils/constants'

const { Text } = Typography

const STATUS_CONFIG = {
  success: { color: 'success', text: '成功', icon: <CheckCircleFilled /> },
  partial: { color: 'warning', text: '部分成功', icon: <ExclamationCircleOutlined /> },
  failed: { color: 'error', text: '失败', icon: <CloseCircleFilled /> },
  skipped: { color: 'default', text: '已跳过', icon: <PauseCircleOutlined /> },
}

const CATEGORY_TAG = {
  api: { color: 'blue', text: 'API' },
  local: { color: 'purple', text: '本地' },
}

const DataSourceTab = () => {
  const [shops, setShops] = useState([])
  const [shopId, setShopId] = useState(null)
  const [shopDetail, setShopDetail] = useState(null)
  const [dataSources, setDataSources] = useState([])
  const [sharedSources, setSharedSources] = useState([])
  const [loading, setLoading] = useState(false)

  // 弹窗状态
  const [pauseModal, setPauseModal] = useState({ open: false, type: null, sourceKey: null })
  const [pauseForm] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)
  // 手动更新中的 source_key 集合 (UI loading 状态)
  const [triggering, setTriggering] = useState(new Set())

  // 加载店铺列表
  useEffect(() => {
    (async () => {
      try {
        const res = await getShops({ page: 1, page_size: 100 })
        const items = res.data?.items || []
        // 2026-05-03 老板拍：店铺选择器按平台排序 Ozon > WB > Yandex,同平台内按名字
        const PLATFORM_ORDER = { ozon: 1, wb: 2, yandex: 3 }
        items.sort((a, b) => {
          const oa = PLATFORM_ORDER[a.platform] ?? 99
          const ob = PLATFORM_ORDER[b.platform] ?? 99
          if (oa !== ob) return oa - ob
          return (a.name || '').localeCompare(b.name || '')
        })
        setShops(items)
        if (items.length && !shopId) setShopId(items[0].id)
      } catch (err) {
        message.error('获取店铺列表失败')
      }
    })()
  }, []) // eslint-disable-line

  const fetchShopData = useCallback(async () => {
    if (!shopId) return
    setLoading(true)
    try {
      const [r1, r2] = await Promise.all([
        getShopDataSources(shopId),
        getSharedDataSources(),
      ])
      setShopDetail(r1.data?.shop || null)
      setDataSources(r1.data?.data_sources || [])
      setSharedSources(r2.data?.data_sources || [])
    } catch (err) {
      message.error(err.message || '加载数据源失败')
    } finally {
      setLoading(false)
    }
  }, [shopId])

  useEffect(() => { fetchShopData() }, [fetchShopData])

  // ========== Level 1: 店铺 API 总开关 ==========
  const handleShopApiToggle = (checked) => {
    if (checked) {
      // 启用,直接调
      Modal.confirm({
        title: '确认启用该店铺的 API 调用?',
        content: '启用后所有 API 类数据源将恢复定时同步。',
        onOk: async () => {
          try {
            await patchShopApiSwitch(shopId, { enabled: true })
            message.success('已启用')
            fetchShopData()
          } catch (err) { message.error(err.message || '操作失败') }
        },
      })
    } else {
      // 禁用,弹窗填原因
      setPauseModal({ open: true, type: 'shop', sourceKey: null })
      pauseForm.resetFields()
    }
  }

  // ========== 手动触发同步 ==========
  const handleManualTrigger = async (sourceKey, sourceLabel) => {
    setTriggering(prev => new Set(prev).add(sourceKey))
    try {
      const r = await triggerSyncDataSource(shopId, sourceKey)
      message.success(`已派发"${sourceLabel}"后台执行,稍后看"最近同步"列查结果`)
      // 5 秒后刷新一次状态 (大部分快任务能跑完)
      setTimeout(() => fetchShopData(), 5000)
    } catch (err) {
      message.error(err.message || '派发失败')
    } finally {
      setTriggering(prev => {
        const next = new Set(prev)
        next.delete(sourceKey)
        return next
      })
    }
  }

  // ========== Level 2: 单数据源开关 ==========
  const handleSourceToggle = (sourceKey, checked) => {
    if (checked) {
      Modal.confirm({
        title: '确认启用该数据源?',
        onOk: async () => {
          try {
            await patchDataSource(shopId, sourceKey, { enabled: true })
            message.success('已启用')
            fetchShopData()
          } catch (err) { message.error(err.message || '操作失败') }
        },
      })
    } else {
      setPauseModal({ open: true, type: 'source', sourceKey })
      pauseForm.resetFields()
    }
  }

  const handlePauseSubmit = async () => {
    try {
      const values = await pauseForm.validateFields()
      setSubmitting(true)
      if (pauseModal.type === 'shop') {
        await patchShopApiSwitch(shopId, {
          enabled: false,
          reason: values.reason,
          auto_resume_hours: values.auto_resume_hours || null,
        })
      } else {
        await patchDataSource(shopId, pauseModal.sourceKey, {
          enabled: false,
          reason: values.reason,
        })
      }
      message.success('已暂停')
      setPauseModal({ open: false, type: null, sourceKey: null })
      fetchShopData()
    } catch (err) {
      if (err.errorFields) return
      message.error(err.message || '操作失败')
    } finally { setSubmitting(false) }
  }

  // ========== 数据源 Table 列 ==========
  const sourceColumns = [
    {
      title: '状态',
      key: 'effective',
      width: 90,
      render: (_, r) => {
        if (!r.effective_enabled) {
          // 拆开判断: Level 1 关 vs Level 2 关
          if (r.category === 'api' && shopDetail && !shopDetail.api_enabled) {
            return <Tag color="default" icon={<PauseCircleOutlined />}>店关</Tag>
          }
          return <Tag color="error" icon={<PauseCircleOutlined />}>暂停</Tag>
        }
        return <Tag color="success" icon={<CheckCircleFilled />}>运行中</Tag>
      },
    },
    {
      title: '数据源',
      dataIndex: 'label',
      key: 'label',
      render: (text, r) => (
        <div>
          <div style={{ fontWeight: 500 }}>
            {text}
            <Tag color={CATEGORY_TAG[r.category]?.color} style={{ marginLeft: 8 }}>
              {CATEGORY_TAG[r.category]?.text}
            </Tag>
          </div>
          <div style={{ fontSize: 12, color: '#999', marginTop: 2 }}>
            {r.depends?.length ? `依赖: ${r.depends.join(' / ')}` : '无依赖'}
          </div>
        </div>
      ),
    },
    {
      title: '调度',
      dataIndex: 'schedule_desc',
      key: 'schedule_desc',
      width: 200,
      render: (v, r) => r.manual_only ? (
        <Space size={4}>
          <Tag color="orange" icon={<ThunderboltOutlined />} style={{ marginRight: 0 }}>手动触发</Tag>
          <span style={{ fontSize: 12, color: '#999' }}>用户点同步按钮</span>
        </Space>
      ) : (
        <Space size={4}>
          <ClockCircleOutlined style={{ color: '#999' }} />
          <span style={{ fontSize: 13 }}>{v}</span>
        </Space>
      ),
    },
    {
      title: '最近同步',
      key: 'last_sync',
      width: 240,
      render: (_, r) => {
        if (!r.last_sync_at) {
          return <Text type="secondary" style={{ fontSize: 12 }}>暂无记录</Text>
        }
        const cfg = STATUS_CONFIG[r.last_sync_status] || { color: 'default', text: r.last_sync_status }
        return (
          <Space direction="vertical" size={2}>
            <Space size={6}>
              <Badge status={cfg.color} text={cfg.text} />
              <Text style={{ fontSize: 12, color: '#666' }}>{formatMoscowTime(r.last_sync_at)}</Text>
            </Space>
            {r.last_sync_rows ? (
              <Text style={{ fontSize: 12, color: '#999' }}>{r.last_sync_rows} 行</Text>
            ) : null}
            {r.last_sync_msg ? (
              <Tooltip title={r.last_sync_msg}>
                <Text ellipsis style={{ fontSize: 12, color: '#999', maxWidth: 220, display: 'block' }}>
                  {r.last_sync_msg}
                </Text>
              </Tooltip>
            ) : null}
          </Space>
        )
      },
    },
    {
      title: '开关',
      key: 'switch',
      width: 90,
      render: (_, r) => {
        // 总开关压制 (Level 1 关 + 此源是 API 类) → Switch 强制 disabled,提示用户
        const apiSuppressed = r.category === 'api' && shopDetail && !shopDetail.api_enabled
        const tip = apiSuppressed
          ? '店铺 API 总开关关闭中,此开关暂被压制不生效'
          : (r.manual_hold_reason ? `暂停原因: ${r.manual_hold_reason}` : '')
        return (
          <Tooltip title={tip}>
            <Switch
              checked={r.enabled}
              disabled={apiSuppressed}
              onChange={(c) => handleSourceToggle(r.key, c)}
            />
          </Tooltip>
        )
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 110,
      render: (_, r) => {
        // 自动屏蔽托管暂不支持单店触发(只能按活动级)
        const unsupported = r.key === 'wb_ad_auto_exclude'
        const disabled = unsupported || !r.effective_enabled
        const tip = unsupported
          ? '请到广告管理 → 活动详情 → "立即跑一次" 按钮按活动触发'
          : (!r.effective_enabled ? '已暂停或被总开关压制,无法手动更新' : '立即派发后台同步')
        return (
          <Tooltip title={tip}>
            <Button
              type="link"
              size="small"
              icon={<SyncOutlined spin={triggering.has(r.key)} />}
              loading={triggering.has(r.key)}
              disabled={disabled}
              onClick={() => handleManualTrigger(r.key, r.label)}
            >
              更新
            </Button>
          </Tooltip>
        )
      },
    },
  ]

  // ========== 顶部店铺级 banner ==========
  const renderShopBanner = () => {
    if (!shopDetail) return null
    const platformInfo = PLATFORMS[shopDetail.platform]
    const apiOff = !shopDetail.api_enabled

    return (
      <Card
        size="small"
        style={{
          marginBottom: 16,
          background: apiOff ? '#fff2f0' : '#f6ffed',
          borderColor: apiOff ? '#ffccc7' : '#b7eb8f',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Space size={12}>
            <ShopOutlined style={{ fontSize: 18 }} />
            <span style={{ fontWeight: 600, fontSize: 15 }}>{shopDetail.name}</span>
            {platformInfo && <Tag color={platformInfo.color}>{platformInfo.label}</Tag>}
            <Divider type="vertical" />
            <Text strong>店铺 API 总开关:</Text>
            <Switch
              checked={shopDetail.api_enabled}
              onChange={handleShopApiToggle}
              checkedChildren="启用"
              unCheckedChildren="禁用"
            />
            <Tag color={apiOff ? 'red' : 'green'} icon={<ApiOutlined />}>
              {apiOff ? '已禁用 (所有 API 类数据源不会跑)' : '运行中'}
            </Tag>
          </Space>
          <Button icon={<ReloadOutlined />} onClick={fetchShopData} size="small">刷新</Button>
        </div>

        {apiOff && (
          <Alert
            type="warning"
            showIcon
            style={{ marginTop: 12 }}
            message={
              <Space direction="vertical" size={2}>
                <span>禁用原因: <b>{shopDetail.api_disabled_reason || '未填写'}</b></span>
                <span style={{ fontSize: 12, color: '#666' }}>
                  禁用时间: {formatMoscowTime(shopDetail.api_disabled_at)}
                  {shopDetail.api_disabled_until && (
                    <span style={{ marginLeft: 16 }}>
                      自动恢复: {formatMoscowTime(shopDetail.api_disabled_until)}
                    </span>
                  )}
                </span>
              </Space>
            }
          />
        )}
      </Card>
    )
  }

  // ========== 共享数据源卡片 ==========
  const renderSharedCard = () => (
    <Card
      size="small"
      title={<Space><GlobalOutlined /><span>跨店共享数据源</span></Space>}
      style={{ marginTop: 16 }}
      bodyStyle={{ padding: '8px 0' }}
    >
      {sharedSources.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无共享数据源" />
      ) : (
        <Table
          columns={sourceColumns.filter(c => c.key !== 'switch' && c.key !== 'action').concat([{
            title: '开关',
            key: 'switch',
            width: 90,
            render: (_, r) => (
              <Tooltip title={r.manual_hold_reason ? `暂停原因: ${r.manual_hold_reason}` : '共享数据源 (跨店生效)'}>
                <Switch
                  checked={r.enabled}
                  disabled
                />
              </Tooltip>
            ),
          }])}
          dataSource={sharedSources}
          rowKey="key"
          pagination={false}
          size="small"
        />
      )}
    </Card>
  )

  return (
    <div>
      {/* 顶部说明 */}
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="2 层权限模型"
        description={
          <div style={{ fontSize: 13 }}>
            <b>店铺 API 总开关 (Level 1)</b>: 关闭后该店所有 API 类数据源全部停跑 (紧急止血用,如 WB 配额耗尽)。<br/>
            <b>单数据源开关 (Level 2)</b>: 单独控制每个数据源,本地类数据源不受 Level 1 影响。
          </div>
        }
      />

      {/* 店铺选择 */}
      <Space style={{ marginBottom: 16 }}>
        <span>选择店铺:</span>
        <Select
          style={{ width: 280 }}
          value={shopId}
          onChange={setShopId}
          options={shops.map(s => ({
            value: s.id,
            label: (
              <Space>
                <Tag color={PLATFORMS[s.platform]?.color}>{PLATFORMS[s.platform]?.label}</Tag>
                <span>{s.name}</span>
              </Space>
            ),
          }))}
          placeholder="选择店铺"
        />
      </Space>

      {/* 店铺级 banner */}
      {renderShopBanner()}

      {/* 数据源 Table */}
      <Card size="small" bodyStyle={{ padding: 0 }}>
        <Table
          columns={sourceColumns}
          dataSource={dataSources}
          rowKey="key"
          loading={loading}
          pagination={false}
          locale={{ emptyText: shopId ? '该店铺暂无数据源' : '请先选择店铺' }}
        />
      </Card>

      {/* 共享数据源 */}
      {renderSharedCard()}

      {/* 暂停弹窗 (Level 1 / Level 2 共用) */}
      <Modal
        title={pauseModal.type === 'shop' ? '禁用店铺 API 调用' : '暂停数据源'}
        open={pauseModal.open}
        onOk={handlePauseSubmit}
        onCancel={() => setPauseModal({ open: false, type: null, sourceKey: null })}
        confirmLoading={submitting}
        width={480}
        destroyOnClose
      >
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={
            pauseModal.type === 'shop'
              ? '禁用后该店所有 API 类数据源将停跑,本地类不受影响'
              : '暂停后该数据源在下次定时调度时会被 skip'
          }
        />
        <Form form={pauseForm} layout="vertical">
          <Form.Item
            name="reason"
            label="原因 (展示给所有人看)"
            rules={[{ required: true, message: '必填' }, { max: 500 }]}
          >
            <Input.TextArea
              rows={3}
              placeholder="如: WB seller quota 耗尽,等待 24h 重置"
            />
          </Form.Item>
          {pauseModal.type === 'shop' && (
            <Form.Item
              name="auto_resume_hours"
              label="N 小时后自动启用 (留空 = 手动启用)"
              extra="范围 1-720 小时 (最长 30 天)"
            >
              <InputNumber min={1} max={720} style={{ width: 200 }} placeholder="例如: 24" />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  )
}

export default DataSourceTab
