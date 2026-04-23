import { useState, useEffect, useRef } from 'react'
import { formatMoscowHourMinute } from '@/utils/time'
import AdsAIPricing from './AdsAIPricing'
import {
  Button, Modal, message, Empty,
  Table, Tag, Tooltip, Space,
  InputNumber, Collapse, Spin, Badge,
  Card, Row, Col, Select, Alert,
} from 'antd'
import {
  getDashboard, getTimePricing, updateTimePricing,
  enableTimePricing, disableTimePricing,
  getTimePricingStatus, restoreSku,
  checkConflict, getBidLogs,
} from '@/api/bid_management'

// ==========================================
// 常量配置
// ==========================================
const HOURS = Array.from({ length: 24 }, (_, i) => i)
// 4档时段语义：高峰/次高峰/低谷 + 未配置=平谷期(保持原价不动)
// 默认值与后端 GET /time-pricing/{shop_id} 无规则时返回的一致
const DEFAULT_PEAK_HOURS = [10, 11, 12, 13, 19, 20, 21, 22]
const DEFAULT_MID_HOURS = [7, 8, 9, 14, 15, 16, 17, 18]
const DEFAULT_LOW_HOURS = [0, 1, 2, 3, 4, 5, 6, 23]
const DEFAULT_PEAK_RATIO = 120
const DEFAULT_MID_RATIO = 100
const DEFAULT_LOW_RATIO = 60

// ==========================================
// 状态栏组件
// ==========================================
const StatusBar = ({ shopId }) => {
  const [data, setData] = useState(null)
  const timerRef = useRef(null)

  useEffect(() => {
    fetchDashboard()
    timerRef.current = setInterval(fetchDashboard, 60000)
    return () => clearInterval(timerRef.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shopId])

  const fetchDashboard = async () => {
    try {
      const res = await getDashboard(shopId)
      setData(res.data)
    } catch {
      // 静默失败
    }
  }

  if (!data) return null

  // 把 ISO 8601 时间字符串截成 YYYY-MM-DD HH:mm:ss
  // 例：2026-04-11T11:30:48.791109+03:00 → 2026-04-11 11:30:48
  const formatTime = (iso) => {
    if (!iso) return '-'
    const m = iso.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})/)
    return m ? `${m[1]} ${m[2]}` : iso
  }

  const items = [
    { label: '莫斯科时间', value: formatTime(data.moscow_time), color: '#534AB7' },
    { label: '当前时段', value: data.current_period_name || '基准期' },
    {
      label: '下次执行',
      value: `${data.next_execute_at}（${data.next_execute_minutes}分钟后）`,
      color: '#3B6D11',
    },
    {
      label: '上次执行',
      value: data.last_executed_at ? formatMoscowHourMinute(data.last_executed_at) : '-',
    },
    {
      label: '执行结果',
      value: data.last_execute_result || '-',
      color: data.last_execute_status === 'failed' ? '#A32D2D'
        : data.last_execute_status === 'success' ? '#3B6D11'
        : 'var(--color-text-primary, #262626)',
    },
  ]

  return (
    <div style={{
      display: 'flex',
      border: '0.5px solid var(--color-border-tertiary, #e8e8e8)',
      borderRadius: 6,
      overflow: 'hidden',
      marginBottom: 14,
    }}>
      {items.map((item, i) => (
        <div key={i} style={{
          flex: 1,
          padding: '9px 14px',
          borderRight: i < items.length - 1 ? '0.5px solid var(--color-border-tertiary, #e8e8e8)' : 'none',
          display: 'flex',
          flexDirection: 'column',
          gap: 2,
          background: 'var(--color-background-secondary, #fafafa)',
        }}>
          <span style={{ fontSize: 11, color: 'var(--color-text-tertiary, #999)' }}>
            {item.label}
          </span>
          <span style={{
            fontSize: 13,
            fontWeight: 500,
            color: item.color || 'var(--color-text-primary, #262626)',
          }}>
            {item.value}
          </span>
        </div>
      ))}
    </div>
  )
}

// ==========================================
// 模式选择卡片
// ==========================================
const ModeSelector = ({ activeMode, onSelect }) => {
  const modes = [
    {
      key: 'time_pricing',
      title: '分时调价',
      desc: '按莫斯科时间设置各时段出价系数，高峰加价，低谷降价，规则固定机械执行。',
      chip: '适合有明确流量规律',
      chipStyle: { background: '#FAEEDA', color: '#633806' },
    },
    {
      key: 'ai',
      title: 'AI智能调价',
      desc: '基于ROAS数据智能分析，识别商品阶段，结合时段规律，动态给出最优出价。',
      chip: '适合追求ROI最大化',
      chipStyle: { background: '#EEEDFE', color: '#3C3489' },
    },
  ]

  return (
    <div>
      <div style={{
        fontSize: 12,
        color: 'var(--color-text-secondary, #666)',
        marginBottom: 8,
      }}>
        选择出价模式（二选一，保存开启时检测冲突）
      </div>
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: 10,
        marginBottom: 14,
      }}>
        {modes.map(mode => {
          const isActive = activeMode === mode.key
          return (
            <div
              key={mode.key}
              onClick={() => onSelect(mode.key)}
              style={{
                border: isActive ? '2px solid #534AB7' : '0.5px solid var(--color-border-tertiary, #e8e8e8)',
                borderRadius: 8,
                padding: 14,
                cursor: 'pointer',
                background: isActive ? '#EEEDFE' : 'var(--color-background-primary, #fff)',
              }}
            >
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                marginBottom: 6,
              }}>
                <div style={{
                  width: 15, height: 15,
                  borderRadius: '50%',
                  border: `2px solid ${isActive ? '#534AB7' : 'var(--color-border-secondary, #d9d9d9)'}`,
                  background: isActive ? '#534AB7' : 'transparent',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                }}>
                  {isActive && (
                    <div style={{ width: 5, height: 5, borderRadius: '50%', background: '#fff' }} />
                  )}
                </div>
                <span style={{
                  fontSize: 14,
                  fontWeight: 500,
                  color: isActive ? '#3C3489' : 'var(--color-text-primary, #262626)',
                }}>
                  {mode.title}
                </span>
              </div>
              <div style={{
                fontSize: 12,
                color: isActive ? '#534AB7' : 'var(--color-text-secondary, #666)',
                lineHeight: 1.5,
                marginBottom: 8,
              }}>
                {mode.desc}
              </div>
              <span style={{
                display: 'inline-block',
                fontSize: 11,
                padding: '2px 8px',
                borderRadius: 20,
                ...mode.chipStyle,
              }}>
                {mode.chip}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ==========================================
// 调价历史组件（分时+AI合并）
// ==========================================
const BidLogs = ({ shopId, refreshKey }) => {
  const [logs, setLogs] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    loadLogs()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shopId, page, refreshKey])

  const loadLogs = async () => {
    setLoading(true)
    try {
      const res = await getBidLogs(shopId, { page, size: 20, execute_type: 'all' })
      // 后端响应：{ total, page, size, items: [...] }
      setLogs(res.data?.items || [])
      setTotal(res.data?.total || 0)
    } catch {
      setLogs([])
    } finally {
      setLoading(false)
    }
  }

  const TYPE_CONFIG = {
    time_pricing:  { color: 'blue', label: '分时调价' },
    time_restore:  { color: 'cyan', label: '分时恢复' },
    ai_auto:       { color: 'purple', label: 'AI自动' },
    ai_manual:     { color: 'geekblue', label: 'AI建议确认' },
    user_manual:   { color: 'default', label: '用户手动' },
  }

  const columns = [
    { title: '时间', dataIndex: 'created_at', width: 100, render: v => v ? formatMoscowHourMinute(v) : '-' },
    {
      title: '活动 / 商品',
      key: 'name',
      render: (_, r) => (
        <div>
          <div style={{ fontSize: 12, fontWeight: 500 }}>{r.campaign_name}</div>
          <Tooltip title={r.sku_name}>
            <div style={{
              fontSize: 11,
              color: 'var(--color-text-secondary, #666)',
              maxWidth: 160,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}>
              {r.sku_name}
            </div>
          </Tooltip>
        </div>
      ),
    },
    { title: '调前', dataIndex: 'old_bid', width: 70, render: v => `₽${v}` },
    {
      title: '调后', dataIndex: 'new_bid', width: 70,
      render: (v, r) => (
        <span style={{
          color: r.adjust_pct > 0 ? '#3B6D11' : '#A32D2D',
          fontWeight: 500,
        }}>₽{v}</span>
      ),
    },
    {
      title: '调幅', dataIndex: 'adjust_pct', width: 80,
      render: v => {
        const up = v > 0
        return (
          <span style={{
            background: up ? '#EAF3DE' : '#FCEBEB',
            color: up ? '#27500A' : '#791F1F',
            padding: '2px 7px',
            borderRadius: 20,
            fontSize: 11,
          }}>
            {up ? '↑' : '↓'}{Math.abs(v).toFixed(1)}%
          </span>
        )
      },
    },
    {
      title: '执行方式', dataIndex: 'execute_type', width: 100,
      render: v => {
        const cfg = TYPE_CONFIG[v] || { color: 'default', label: v }
        return <Tag color={cfg.color}>{cfg.label}</Tag>
      },
    },
    {
      title: '状态', dataIndex: 'success', width: 70,
      render: (v, r) => {
        const tag = <Tag color={v ? 'green' : 'red'} style={{ cursor: 'help' }}>{v ? '成功' : '失败'}</Tag>
        // 悬停显示 AI 调价的决策理由（或分时调价的时段语义）
        // reason 为 null 说明是 cutover 前的历史记录，提示一下
        const tipContent = r.reason
          ? (
              <div style={{ maxWidth: 460, whiteSpace: 'pre-wrap', lineHeight: 1.6, fontSize: 12 }}>
                {!v && r.error_msg && (
                  <div style={{ color: '#FFB4B4', marginBottom: 6 }}>
                    ⚠ 错误：{r.error_msg}
                  </div>
                )}
                <div>{r.reason}</div>
              </div>
            )
          : (!v && r.error_msg
              ? <div style={{ maxWidth: 400, fontSize: 12 }}>⚠ {r.error_msg}</div>
              : <span style={{ fontSize: 12, color: '#bbb' }}>无详细理由（历史记录）</span>)
        return <Tooltip title={tipContent} placement="left">{tag}</Tooltip>
      },
    },
  ]

  return (
    <Collapse style={{ marginTop: 10 }}>
      <Collapse.Panel
        key="logs"
        header={
          <span>
            调价历史记录
            <span style={{
              fontSize: 12,
              color: 'var(--color-text-secondary, #666)',
              fontWeight: 400,
              marginLeft: 8,
            }}>
              （分时调价 + AI调价 合并显示）
            </span>
          </span>
        }
      >
        <Table
          dataSource={logs}
          columns={columns}
          rowKey="id"
          loading={loading}
          size="small"
          scroll={{ x: 700 }}
          pagination={{
            current: page,
            total,
            pageSize: 20,
            onChange: setPage,
            showTotal: t => `共${t}条`,
          }}
        />
      </Collapse.Panel>
    </Collapse>
  )
}

// ==========================================
// 分时调价配置组件
// ==========================================
const TimePricingConfig = ({ shopId, platform, activeMode, onSaved }) => {
  const platformLabel = platform === 'wb' ? 'WB' : 'Ozon'
  const [localEnabled, setLocalEnabled] = useState(null)
  const isEnabled = localEnabled !== null ? localEnabled : activeMode === 'time_pricing'

  // 父组件 activeMode 变化时同步
  useEffect(() => { setLocalEnabled(null) }, [activeMode])
  const [peakHours, setPeakHours] = useState(DEFAULT_PEAK_HOURS)
  const [midHours, setMidHours] = useState(DEFAULT_MID_HOURS)
  const [lowHours, setLowHours] = useState(DEFAULT_LOW_HOURS)
  const [peakRatio, setPeakRatio] = useState(DEFAULT_PEAK_RATIO)
  const [midRatio, setMidRatio] = useState(DEFAULT_MID_RATIO)
  const [lowRatio, setLowRatio] = useState(DEFAULT_LOW_RATIO)
  const [saving, setSaving] = useState(false)
  const [savingMsg, setSavingMsg] = useState('')
  const [statusData, setStatusData] = useState([])

  useEffect(() => {
    loadConfig()
    loadStatus()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shopId])

  const loadConfig = async () => {
    try {
      const res = await getTimePricing(shopId)
      const d = res.data || {}
      if (d.peak_hours) setPeakHours(typeof d.peak_hours === 'string' ? JSON.parse(d.peak_hours) : d.peak_hours)
      if (d.mid_hours) setMidHours(typeof d.mid_hours === 'string' ? JSON.parse(d.mid_hours) : d.mid_hours)
      if (d.low_hours) setLowHours(typeof d.low_hours === 'string' ? JSON.parse(d.low_hours) : d.low_hours)
      if (d.peak_ratio) setPeakRatio(d.peak_ratio)
      if (d.mid_ratio) setMidRatio(d.mid_ratio)
      if (d.low_ratio) setLowRatio(d.low_ratio)
    } catch {
      // 静默失败
    }
  }

  const loadStatus = async () => {
    try {
      const res = await getTimePricingStatus(shopId)
      // 后端响应：{ campaigns: [{ campaign_id, campaign_name, skus: [...] }] }
      setStatusData(res.data?.campaigns || [])
    } catch {
      setStatusData([])
    }
  }

  // 生成 24 小时下拉选项，已被其他档位占用的小时 disabled
  const hourOpts = (excludeA, excludeB) => {
    const used = new Set([...excludeA, ...excludeB])
    return HOURS.map(i => ({
      value: i,
      label: `${String(i).padStart(2, '0')}:00`,
      disabled: used.has(i),
    }))
  }

  // 4 档时段语义：三档不重叠即可，未配置的小时归为平谷期(保持原价不动)
  const validateHoursLocal = () => {
    const all = [...peakHours, ...midHours, ...lowHours]
    if (all.length !== new Set(all).size) {
      message.error('同一小时不能同时属于多个时段')
      return false
    }
    for (const h of all) {
      if (h < 0 || h > 23) {
        message.error('小时必须在 0-23 之间')
        return false
      }
    }
    for (const r of [peakRatio, midRatio, lowRatio]) {
      if (r < 10 || r > 500) {
        message.error('系数必须在 10% - 500% 之间')
        return false
      }
    }
    return true
  }

  const handleSaveAndEnable = async () => {
    if (!validateHoursLocal()) return
    try {
      const conflictRes = await checkConflict(shopId, 'time_pricing')
      if (conflictRes.data?.conflict) {
        // #15 修复：冲突时不再提供"确认开启"误导按钮，
        // 引导用户去停用对应模式（无 onOk 强制开启路径）
        Modal.warning({
          title: '规则冲突，无法开启',
          content: (
            <div>
              <p>{conflictRes.data.message}</p>
              <p style={{ marginTop: 12, color: '#999', fontSize: 13 }}>
                请先到 AI 调价 Tab 停用 AI 调价，然后再回来开启分时调价。
              </p>
            </div>
          ),
          okText: '我知道了',
        })
        return
      }
    } catch {
      // 冲突检测接口失败时仍继续保存（容错）
    }
    await doSaveAndEnable()
  }

  /** 计算莫斯科当前小时（UTC+3） */
  const getMoscowHour = () => {
    const now = new Date()
    const utcH = now.getUTCHours()
    return (utcH + 3) % 24
  }

  const doSaveAndEnable = async () => {
    setSaving(true)
    setSavingMsg('正在保存配置...')
    try {
      await updateTimePricing(shopId, {
        peak_hours: peakHours,
        mid_hours: midHours,
        low_hours: lowHours,
        peak_ratio: peakRatio,
        mid_ratio: midRatio,
        low_ratio: lowRatio,
      })
      setSavingMsg('正在启用分时调价并执行首次调价...')
      setLocalEnabled(true)
      await enableTimePricing(shopId)
      setSavingMsg('正在刷新执行状态...')
      await loadStatus()
      message.success('分时调价已开启')
      onSaved?.()
    } catch (e) {
      setLocalEnabled(false)
      message.error(e?.message || '保存失败')
    } finally {
      setSaving(false)
      setSavingMsg('')
    }
  }

  // 状态表格列
  const statusColumns = [
    {
      title: '活动 / 商品',
      key: 'name',
      render: (_, record) => record.isGroup ? (
        <span style={{ fontWeight: 500 }}>
          {record.campaign_name}
          <span style={{
            fontWeight: 400,
            fontSize: 11,
            color: 'var(--color-text-secondary, #666)',
            marginLeft: 8,
          }}>
            ID:{record.campaign_id}
          </span>
        </span>
      ) : (
        <div style={{ paddingLeft: 20 }}>
          <Tooltip title={record.sku_name || record.platform_sku_id}>
            <span style={{
              fontSize: 12,
              color: 'var(--color-text-secondary, #666)',
              cursor: 'help',
            }}>
              {record.platform_sku_id}
            </span>
          </Tooltip>
        </div>
      ),
    },
    {
      title: '原始出价', dataIndex: 'original_bid', width: 90,
      render: (v, r) => r.isGroup ? null : `₽${v || 0}`,
    },
    {
      title: '当前出价', dataIndex: 'current_bid', width: 90,
      render: (v, r) => r.isGroup ? null : `₽${v || 0}`,
    },
    {
      title: '状态', width: 140,
      render: (_, r) => {
        if (r.isGroup) return null
        if (r.user_managed) return <Badge status="warning" text="用户管理" />
        if (r.min_bid_limited) return <Badge color="orange" text="受限于最低出价" />
        return <Badge status="success" text="正常执行" />
      },
    },
    {
      title: '操作', width: 90,
      render: (_, r) => {
        if (r.isGroup || !r.user_managed) return null
        return (
          <Button
            type="link"
            size="small"
            onClick={async () => {
              try {
                await restoreSku(shopId, r.platform_sku_id)
                message.success('已恢复系统自动管理')
                loadStatus()
              } catch (e) {
                message.error(e?.message || '操作失败')
              }
            }}
          >
            恢复自动
          </Button>
        )
      },
    },
  ]

  // 状态数据展开为表格行
  const statusRows = []
  statusData.forEach(group => {
    statusRows.push({
      key: `g-${group.campaign_id}`,
      isGroup: true,
      ...group,
    })
    ;(group.skus || []).forEach(sku => {
      statusRows.push({
        key: `s-${group.campaign_id}-${sku.platform_sku_id}`,
        isGroup: false,
        ...sku,
      })
    })
  })

  return (
    <div>
      {/* 使用说明（可折叠） */}
      <Collapse style={{ marginBottom: 10 }}>
        <Collapse.Panel key="guide" header="使用说明（点击展开）">
          <div style={{ fontSize: 13, lineHeight: 1.8, color: 'var(--color-text-primary, #333)' }}>
            <div style={{ fontWeight: 500, marginBottom: 4 }}>开启后的运行规则</div>
            <ul style={{ paddingLeft: 20, margin: '0 0 12px' }}>
              <li>系统<b>每小时</b>自动检查一次（莫斯科时间每小时第 5 分钟执行）</li>
              <li>只调整当前店铺 <b>{platformLabel}</b> 平台的<b>活跃广告活动</b>中的商品</li>
              <li>出价公式：<b>商品原始出价 × 当前时段的出价系数</b>（最低不低于 ₽3）</li>
              <li>首次执行时系统会自动记录每个商品的「原始出价」作为基准，后续都按原始出价乘以系数</li>
            </ul>
            <div style={{ fontWeight: 500, marginBottom: 4 }}>以下商品会被跳过，不调价</div>
            <ul style={{ paddingLeft: 20, margin: '0 0 12px' }}>
              <li>标记为「用户管理」的商品 —— 您在下方执行状态表中可以手动标记或恢复</li>
              <li>有人在 {platformLabel} 后台手动改过出价的商品 —— 系统检测到出价被人为修改后会自动标记为用户管理并跳过</li>
              <li>调整后出价与当前出价差值小于 ₽1 的商品 —— 变化太小，不执行</li>
              <li>当前时间不在任何时段（高峰/次高峰/低谷）内的小时为「平谷期」 —— 保持原价不动</li>
            </ul>
            <div style={{ fontWeight: 500, marginBottom: 4 }}>关闭分时调价后</div>
            <ul style={{ paddingLeft: 20, margin: 0 }}>
              <li>系统会自动将所有已被调过的商品出价<b>恢复到开启前的原始出价</b></li>
              <li>如有个别商品恢复失败（{platformLabel} API 异常），会在弹窗中提示，您可在「当前执行状态」表中手动点「恢复原价」重试</li>
            </ul>
          </div>
        </Collapse.Panel>
      </Collapse>

      {/* 时段配置（可折叠） */}
      <Collapse defaultActiveKey={['config']} style={{ marginBottom: 10 }}>
        <Collapse.Panel key="config" header="规则条件">
          <Alert
            message="根据莫斯科时间自动调整出价：高峰加价抢流量，低谷降价省预算，未配置的时段为平谷期保持原价不动"
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
          />

          {/* 高峰时段 */}
          <Card
            size="small"
            title="高峰时段"
            style={{ marginBottom: 12, borderLeft: '3px solid #ff4d4f' }}
          >
            <Row gutter={16}>
              <Col span={16}>
                <div style={{ fontSize: 13, marginBottom: 6, color: 'var(--color-text-secondary, #666)' }}>
                  时间范围
                </div>
                <Select
                  mode="multiple"
                  placeholder="选择小时"
                  value={peakHours}
                  onChange={vs => setPeakHours([...vs].sort((a, b) => a - b))}
                  options={hourOpts(midHours, lowHours)}
                  style={{ width: '100%' }}
                />
              </Col>
              <Col span={8}>
                <div style={{ fontSize: 13, marginBottom: 6, color: 'var(--color-text-secondary, #666)' }}>
                  出价系数
                </div>
                <InputNumber
                  value={peakRatio}
                  onChange={v => setPeakRatio(v ?? 0)}
                  min={0} max={200} step={1} precision={0}
                  style={{ width: '100%' }}
                  addonAfter="%"
                />
                <div style={{ fontSize: 11, color: '#EF9F27', marginTop: 4 }}>
                  原价₽50 → ₽{Math.round(50 * peakRatio / 100)}
                </div>
              </Col>
            </Row>
          </Card>

          {/* 次高峰时段 */}
          <Card
            size="small"
            title="次高峰时段"
            style={{ marginBottom: 12, borderLeft: '3px solid #faad14' }}
          >
            <Row gutter={16}>
              <Col span={16}>
                <div style={{ fontSize: 13, marginBottom: 6, color: 'var(--color-text-secondary, #666)' }}>
                  时间范围
                </div>
                <Select
                  mode="multiple"
                  placeholder="选择小时"
                  value={midHours}
                  onChange={vs => setMidHours([...vs].sort((a, b) => a - b))}
                  options={hourOpts(peakHours, lowHours)}
                  style={{ width: '100%' }}
                />
              </Col>
              <Col span={8}>
                <div style={{ fontSize: 13, marginBottom: 6, color: 'var(--color-text-secondary, #666)' }}>
                  出价系数
                </div>
                <InputNumber
                  value={midRatio}
                  onChange={v => setMidRatio(v ?? 0)}
                  min={0} max={200} step={1} precision={0}
                  style={{ width: '100%' }}
                  addonAfter="%"
                />
                <div style={{ fontSize: 11, color: '#378ADD', marginTop: 4 }}>
                  原价₽50 → ₽{Math.round(50 * midRatio / 100)}
                </div>
              </Col>
            </Row>
          </Card>

          {/* 低谷时段 */}
          <Card
            size="small"
            title="低谷时段"
            style={{ marginBottom: 12, borderLeft: '3px solid #1890ff' }}
          >
            <Row gutter={16}>
              <Col span={16}>
                <div style={{ fontSize: 13, marginBottom: 6, color: 'var(--color-text-secondary, #666)' }}>
                  时间范围
                </div>
                <Select
                  mode="multiple"
                  placeholder="选择小时"
                  value={lowHours}
                  onChange={vs => setLowHours([...vs].sort((a, b) => a - b))}
                  options={hourOpts(peakHours, midHours)}
                  style={{ width: '100%' }}
                />
              </Col>
              <Col span={8}>
                <div style={{ fontSize: 13, marginBottom: 6, color: 'var(--color-text-secondary, #666)' }}>
                  出价系数
                </div>
                <InputNumber
                  value={lowRatio}
                  onChange={v => setLowRatio(v ?? 0)}
                  min={0} max={200} step={1} precision={0}
                  style={{ width: '100%' }}
                  addonAfter="%"
                />
                <div style={{ fontSize: 11, color: '#E24B4A', marginTop: 4 }}>
                  原价₽50 → ₽{Math.round(50 * lowRatio / 100)}
                </div>
              </Col>
            </Row>
          </Card>

          <div style={{
            fontSize: 12,
            color: 'var(--color-text-tertiary, #999)',
            marginBottom: 12,
          }}>
            三档时段不能重叠 · 未配置的小时为平谷期，保持原价不动 · 每小时05分莫斯科时间自动执行 · 差值小于₽1不调用API
          </div>

          <Space>
            {isEnabled ? (
              <Button
                danger
                loading={saving}
                onClick={() => {
                  Modal.confirm({
                    title: '确认关闭分时调价？',
                    content: (
                      <div style={{ fontSize: 13, lineHeight: 1.8 }}>
                        <p>关闭后系统会执行以下操作：</p>
                        <ul style={{ paddingLeft: 20, margin: '4px 0' }}>
                          <li>所有已被分时调价的商品将<b>自动恢复到开启前的原始出价</b></li>
                          <li>恢复过程需逐个调用 {platformLabel} API，可能需要几秒钟</li>
                          <li>如有个别商品恢复失败，会在弹窗中提示，可手动重试</li>
                        </ul>
                        <p style={{ color: '#999', marginTop: 8 }}>分时调价的规则配置不会被删除，下次开启仍可使用。</p>
                      </div>
                    ),
                    okText: '确认关闭',
                    okButtonProps: { danger: true },
                    cancelText: '取消',
                    onOk: async () => {
                      setSaving(true)
                      setSavingMsg('正在关闭分时调价，恢复所有商品到原始出价...')
                      try {
                        const res = await disableTimePricing(shopId)
                        const { restored = 0, failed = 0, errors = [] } = res?.data || {}
                        if (failed > 0) {
                          Modal.warning({
                            title: '分时调价已关闭，部分 SKU 回弹失败',
                            content: (
                              <div>
                                <p>成功恢复 {restored} 个 SKU，失败 {failed} 个</p>
                                <p style={{ marginTop: 8, color: '#999', fontSize: 12 }}>
                                  失败的 SKU 仍保留在「当前执行状态」中，可手动点「恢复原价」重试：
                                </p>
                                <ul style={{ marginTop: 8, fontSize: 12, color: '#666' }}>
                                  {errors.map((e, i) => <li key={i}>{e}</li>)}
                                </ul>
                              </div>
                            ),
                            okText: '我知道了',
                          })
                        } else if (restored > 0) {
                          message.success(`分时调价已关闭，已回弹 ${restored} 个 SKU 到原价`)
                        } else {
                          message.success('分时调价已关闭')
                        }
                        setLocalEnabled(false)
                        onSaved?.()
                      } catch (e) {
                        message.error(e?.message || '关闭失败')
                      } finally {
                        setSaving(false)
                        setSavingMsg('')
                      }
                    },
                  })
                }}
              >
                关闭分时调价
              </Button>
            ) : (
              <Button type="primary" loading={saving} onClick={handleSaveAndEnable}>
                保存并开启
              </Button>
            )}
          </Space>
        </Collapse.Panel>
      </Collapse>

      {/* 操作进度遮罩 */}
      <Modal
        open={!!savingMsg}
        footer={null}
        closable={false}
        maskClosable={false}
        width={400}
        styles={{ body: { padding: 0 } }}
      >
        <div style={{ textAlign: 'center', padding: '40px 20px' }}>
          <Spin size="large" />
          <div style={{ marginTop: 20, fontSize: 14, color: '#534AB7', fontWeight: 500 }}>
            {savingMsg}
          </div>
          <div style={{ marginTop: 8, fontSize: 12, color: '#999' }}>
            请勿关闭页面
          </div>
        </div>
      </Modal>

      {/* 执行状态 - 仅在分时调价开启时显示 */}
      {isEnabled && (() => {
        const moscowH = getMoscowHour()
        const allConfigured = new Set([...peakHours, ...midHours, ...lowHours])
        const isBasePeriod = !allConfigured.has(moscowH)

        if (isBasePeriod) {
          // 找下一个时段
          let nextInfo = null
          for (let offset = 1; offset < 25; offset++) {
            const h = (moscowH + offset) % 24
            if (peakHours.includes(h)) { nextInfo = { h, label: '高峰期', ratio: peakRatio, tomorrow: moscowH + offset >= 24 }; break }
            if (midHours.includes(h)) { nextInfo = { h, label: '次高峰期', ratio: midRatio, tomorrow: moscowH + offset >= 24 }; break }
            if (lowHours.includes(h)) { nextInfo = { h, label: '低谷期', ratio: lowRatio, tomorrow: moscowH + offset >= 24 }; break }
          }
          return (
            <div style={{
              background: '#fafafa', border: '0.5px solid #e8e8e8',
              borderRadius: 8, padding: '24px 14px', marginBottom: 10, textAlign: 'center',
            }}>
              <div style={{ fontSize: 14, fontWeight: 500, color: '#666', marginBottom: 8 }}>
                当前莫斯科时间 {String(moscowH).padStart(2, '0')}:00 为平谷期，暂不调价
              </div>
              {nextInfo && (
                <div style={{ fontSize: 13, color: '#999' }}>
                  下次调价：{nextInfo.tomorrow ? '明天' : '今天'} {String(nextInfo.h).padStart(2, '0')}:05（{nextInfo.label}，系数 {nextInfo.ratio}%）
                </div>
              )}
            </div>
          )
        }

        return (
        <div style={{
          background: 'var(--color-background-primary, #fff)',
          border: '0.5px solid var(--color-border-tertiary, #e8e8e8)',
          borderRadius: 8,
          padding: 14,
          marginBottom: 10,
        }}>
          <div style={{
            fontSize: 13,
            fontWeight: 500,
            marginBottom: 10,
            display: 'flex',
            justifyContent: 'space-between',
          }}>
            当前执行状态
            <Button size="small" onClick={loadStatus}>刷新</Button>
          </div>
          <Table
            dataSource={statusRows}
            columns={statusColumns}
            rowKey="key"
            pagination={false}
            size="small"
            scroll={{ x: 600 }}
            rowClassName={r => (r.isGroup ? 'campaign-group-row' : '')}
          />
        </div>
        )
      })()}

      {/* 调价历史 */}
      <BidLogs shopId={shopId} />
    </div>
  )
}

// ==========================================
// 出价管理主页面
// ==========================================
const BidManagement = ({ shopId, platform }) => {
  const [activeMode, setActiveMode] = useState('none')
  // 第一次进入页面默认选中"分时调价"
  const [selectedMode, setSelectedMode] = useState('time_pricing')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (shopId) loadActiveMode()
    else setLoading(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shopId])

  const loadActiveMode = async () => {
    setLoading(true)
    try {
      const res = await getDashboard(shopId)
      const mode = res.data?.active_mode || 'none'
      setActiveMode(mode)
      if (mode !== 'none') setSelectedMode(mode)
    } catch {
      setActiveMode('none')
    } finally {
      setLoading(false)
    }
  }

  if (!shopId) {
    return <Card><Empty description="请选择平台和店铺后点击确定" /></Card>
  }

  if (loading) return <Spin />

  // Ozon + WB 支持出价管理，其他平台占位
  if (platform !== 'ozon' && platform !== 'wb') {
    return (
      <div style={{
        textAlign: 'center',
        padding: '60px 0',
        color: 'var(--color-text-secondary, #666)',
      }}>
        <div style={{ fontSize: 48, marginBottom: 16 }}>🚧</div>
        <div style={{ fontSize: 16, fontWeight: 500 }}>
          Yandex Market出价管理即将上线
        </div>
        <div style={{ fontSize: 13, marginTop: 8 }}>敬请期待</div>
      </div>
    )
  }

  return (
    <div>
      {/* 运行中标识（只在有模式运行时显示） */}
      {activeMode !== 'none' && (
        <div style={{
          display: 'flex', justifyContent: 'flex-end',
          marginBottom: 10,
        }}>
          <span style={{
            background: '#f6ffed',
            color: '#389e0d',
            fontSize: 12,
            padding: '3px 10px',
            borderRadius: 20,
          }}>
            {activeMode === 'time_pricing' ? '分时调价运行中' : 'AI调价运行中'}
          </span>
        </div>
      )}

      {/* 状态栏 */}
      <StatusBar shopId={shopId} />

      {/* 模式选择 */}
      <ModeSelector activeMode={selectedMode} onSelect={setSelectedMode} />

      <div style={{
        height: '0.5px',
        background: 'var(--color-border-tertiary, #e8e8e8)',
        margin: '0 0 14px',
      }} />

      {/* 根据选择展示对应配置 */}
      {selectedMode === 'time_pricing' ? (
        <TimePricingConfig shopId={shopId} platform={platform} activeMode={activeMode} onSaved={loadActiveMode} />
      ) : (
        <AdsAIPricing shopId={shopId} platform={platform} searched={true} />
      )}
    </div>
  )
}

export default BidManagement
