import { useState, useEffect } from 'react'
import {
  Switch, InputNumber, Button,
  Table, Tag, Alert,
  Space, Badge, message,
} from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import {
  getLinkageRule, updateLinkageRule,
  getShopStocks, manualLinkageCheck,
} from '@/api/inventory'

const InventoryLinkage = ({ shopId }) => {
  const [rule, setRule] = useState({
    is_active: false,
    pause_threshold: 10,
    resume_threshold: 20,
  })
  const [stocks, setStocks] = useState([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [checking, setChecking] = useState(false)

  useEffect(() => {
    if (shopId) fetchData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shopId])

  const fetchData = async () => {
    setLoading(true)
    try {
      const [ruleRes, stockRes] = await Promise.all([
        getLinkageRule(shopId),
        getShopStocks(shopId),
      ])
      if (ruleRes?.data) setRule(ruleRes.data)
      setStocks(stockRes?.data || [])
    } catch {
      // 静默失败（后端接口可能尚未就绪）
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await updateLinkageRule(shopId, rule)
      message.success('规则已保存')
    } catch (e) {
      message.error(e?.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleManualCheck = async () => {
    setChecking(true)
    try {
      await manualLinkageCheck(shopId)
      message.success('检查完成')
      const res = await getShopStocks(shopId)
      setStocks(res?.data || [])
    } catch (e) {
      message.error(e?.message || '检查失败')
    } finally {
      setChecking(false)
    }
  }

  // 统计各状态数量
  const pausedCount = stocks.filter(s => s.status === 'paused').length
  const alertCount = stocks.filter(s => s.status === 'alert').length

  // 按状态排序：已暂停 → 预警 → 正常
  const statusOrder = { paused: 0, alert: 1, normal: 2 }
  const sortedStocks = [...stocks].sort(
    (a, b) => (statusOrder[a.status] ?? 99) - (statusOrder[b.status] ?? 99)
  )

  // 库存列表列定义
  const columns = [
    {
      title: '商品SKU',
      dataIndex: 'platform_sku_id',
      width: 140,
      render: (sku, record) => (
        <div>
          <div style={{ fontWeight: 500, fontSize: 13 }}>{sku}</div>
          <div style={{ fontSize: 12, color: 'var(--color-text-secondary, #999)' }}>
            {record.sku_name}
          </div>
        </div>
      ),
    },
    {
      title: '所属活动',
      dataIndex: 'campaign_name',
      ellipsis: true,
    },
    {
      title: '当前库存',
      dataIndex: 'quantity',
      width: 100,
      render: (qty, record) => {
        const color = qty <= record.pause_threshold
          ? '#ff4d4f'
          : qty <= record.pause_threshold * 2
            ? '#faad14'
            : '#52c41a'
        return (
          <span style={{ color, fontWeight: 500, fontSize: 15 }}>
            {qty}件
          </span>
        )
      },
    },
    {
      title: '联动状态',
      dataIndex: 'status',
      width: 120,
      render: status => {
        const config = {
          normal: { status: 'success', text: '正常投放' },
          alert: { status: 'warning', text: '库存预警' },
          paused: { status: 'error', text: '已暂停出价' },
        }[status] || { status: 'default', text: status }
        return <Badge status={config.status} text={config.text} />
      },
    },
    {
      title: '暂停时间',
      dataIndex: 'paused_at',
      width: 140,
      render: v => v
        ? new Date(v).toLocaleString('zh-CN', {
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
          })
        : '-',
    },
    {
      title: '暂停前出价',
      dataIndex: 'paused_bid',
      width: 100,
      render: v => v ? `₽${v}` : '-',
    },
    {
      title: '最后同步',
      dataIndex: 'last_synced_at',
      width: 100,
      render: v => v
        ? new Date(v).toLocaleString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit',
          })
        : '-',
    },
  ]

  return (
    <div>
      {/* 上半部分：规则配置 */}
      <div style={{
        background: 'var(--color-background-secondary, #fafafa)',
        borderRadius: 8,
        padding: '20px 24px',
        marginBottom: 24,
      }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          marginBottom: 20,
        }}>
          <span style={{ fontSize: 15, fontWeight: 500 }}>库存联动</span>
          <Switch
            checked={rule.is_active}
            onChange={v => setRule({ ...rule, is_active: v })}
            checkedChildren="已开启"
            unCheckedChildren="已关闭"
          />
          {rule.is_active && (
            <span style={{ fontSize: 13, color: '#52c41a' }}>
              自动监控该店铺所有活动下的商品库存
            </span>
          )}
        </div>

        {/* 阈值设置 */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 24,
          flexWrap: 'wrap',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 13, color: 'var(--color-text-secondary, #999)' }}>
              平台仓库存低于
            </span>
            <InputNumber
              min={1}
              max={rule.resume_threshold - 1}
              value={rule.pause_threshold}
              onChange={v => setRule({ ...rule, pause_threshold: v })}
              style={{ width: 80 }}
              addonAfter="件"
            />
            <span style={{ fontSize: 13, color: 'var(--color-text-secondary, #999)' }}>
              时自动暂停该商品出价
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 13, color: 'var(--color-text-secondary, #999)' }}>
              库存恢复到
            </span>
            <InputNumber
              min={rule.pause_threshold + 1}
              value={rule.resume_threshold}
              onChange={v => setRule({ ...rule, resume_threshold: v })}
              style={{ width: 80 }}
              addonAfter="件"
            />
            <span style={{ fontSize: 13, color: 'var(--color-text-secondary, #999)' }}>
              以上时自动恢复出价
            </span>
          </div>

          <Button type="primary" onClick={handleSave} loading={saving}>
            保存设置
          </Button>
        </div>

        {/* 说明文字 */}
        <div style={{
          marginTop: 12,
          fontSize: 12,
          color: 'var(--color-text-secondary, #999)',
        }}>
          每天凌晨2点自动检查 · 库存数据从平台仓实时同步 · 暂停出价设为₽3（最低值），恢复时还原暂停前出价
        </div>
      </div>

      {/* 下半部分：当前库存状态 */}
      <div>
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 12,
        }}>
          <Space size={16}>
            <span style={{ fontSize: 15, fontWeight: 500 }}>商品库存状态</span>
            {pausedCount > 0 && (
              <Tag color="error">{pausedCount}个已暂停出价</Tag>
            )}
            {alertCount > 0 && (
              <Tag color="warning">{alertCount}个库存预警</Tag>
            )}
          </Space>

          <Button
            icon={<ReloadOutlined />}
            onClick={handleManualCheck}
            loading={checking}
            size="small"
          >
            立即检查
          </Button>
        </div>

        {/* 未开启时的提示 */}
        {!rule.is_active && (
          <Alert
            type="info"
            showIcon
            message="库存联动未开启"
            description="开启后系统将自动监控所有商品库存，低于阈值时自动暂停出价"
            style={{ marginBottom: 16 }}
          />
        )}

        <Table
          dataSource={sortedStocks}
          columns={columns}
          rowKey="id"
          loading={loading}
          pagination={{
            pageSize: 10,
            showTotal: total => `共${total}个SKU`,
          }}
          rowClassName={record => {
            if (record.status === 'paused') return 'row-paused'
            if (record.status === 'alert') return 'row-alert'
            return ''
          }}
          scroll={{ x: 800 }}
        />
      </div>
    </div>
  )
}

export default InventoryLinkage
