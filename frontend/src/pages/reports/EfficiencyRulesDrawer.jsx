import { useState, useEffect } from 'react'
import {
  Drawer, Button, Space, Card, Row, Col, InputNumber, Typography,
  Alert, message, Popconfirm, Skeleton,
} from 'antd'
import { ReloadOutlined, StarFilled, BulbOutlined, WarningFilled, EyeOutlined } from '@ant-design/icons'
import {
  getEfficiencyRules, setEfficiencyRules, resetEfficiencyRules,
} from '@/api/keyword_stats'

const { Text, Paragraph } = Typography

const FIELDS = [
  {
    group: 'base',
    color: '#13c2c2',
    icon: <EyeOutlined />,
    label: '数据置信度',
    desc: '曝光低于门槛的关键词归"新词/观察中"，不参与 4 档评级',
    rows: [
      { key: 'min_impressions', label: '曝光门槛 ≥', suffix: '次', min: 0, max: 1000000, step: 5 },
    ],
  },
  {
    group: 'star',
    color: '#52c41a',
    icon: <StarFilled />,
    label: '高效词',
    desc: 'CTR 达标 且 CPC 不高于平均',
    rows: [
      { key: 'star_ctr_min', label: 'CTR ≥', suffix: '%', min: 0, max: 100, step: 0.1 },
      { key: 'star_cpc_max_ratio', label: 'CPC ≤ 平均 ×', suffix: '倍', min: 0, max: 10, step: 0.05 },
    ],
  },
  {
    group: 'potential',
    color: '#1677ff',
    icon: <BulbOutlined />,
    label: '潜力词',
    desc: 'CTR 达标 但 曝光偏少（加大投放）',
    rows: [
      { key: 'potential_ctr_min', label: 'CTR ≥', suffix: '%', min: 0, max: 100, step: 0.1 },
      { key: 'potential_impressions_max_ratio', label: '曝光 ≤ 平均 ×', suffix: '倍', min: 0, max: 10, step: 0.05 },
    ],
  },
  {
    group: 'waste',
    color: '#ff4d4f',
    icon: <WarningFilled />,
    label: '浪费词 / 屏蔽规则',
    desc: 'CTR 过低 且 花费超过平均（用于"关键词明细"标注 + "推广信息→活动→商品出价"屏蔽规则）',
    rows: [
      { key: 'waste_ctr_max', label: 'CTR ≤', suffix: '%', min: 0, max: 100, step: 0.1 },
      { key: 'waste_spend_min_ratio', label: '花费 ≥ 平均 ×', suffix: '倍', min: 0, max: 10, step: 0.05 },
      { key: 'waste_min_days', label: '观察 ≥', suffix: '天', min: 1, max: 90, step: 1 },
    ],
  },
]

export default function EfficiencyRulesDrawer({ open, onClose, onSaved }) {
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [rules, setRules] = useState(null)
  const [defaults, setDefaults] = useState(null)
  const [isDefault, setIsDefault] = useState(true)

  useEffect(() => {
    if (!open) return
    setLoading(true)
    getEfficiencyRules()
      .then(r => {
        setRules(r.data?.rules || null)
        setDefaults(r.data?.defaults || null)
        setIsDefault(!!r.data?.is_default)
      })
      .catch(err => message.error(err.message || '加载规则失败'))
      .finally(() => setLoading(false))
  }, [open])

  const setField = (k, v) => setRules(prev => ({ ...prev, [k]: v }))

  const handleSave = async () => {
    if (!rules) return
    setSaving(true)
    try {
      const r = await setEfficiencyRules(rules)
      message.success('规则已保存')
      setIsDefault(!!r.data?.is_default)
      onSaved?.()
      onClose?.()
    } catch (err) {
      message.error(err.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleReset = async () => {
    setSaving(true)
    try {
      const r = await resetEfficiencyRules()
      setRules(r.data?.rules)
      setIsDefault(true)
      message.success('已恢复系统默认')
      onSaved?.()
    } catch (err) {
      message.error(err.message || '恢复失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Drawer
      title="关键词效能评级规则"
      open={open}
      onClose={onClose}
      width={560}
      destroyOnClose
      footer={
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Popconfirm
            title="恢复系统默认？"
            description="删除当前租户的自定义规则，所有关键词按系统默认评级"
            onConfirm={handleReset}
            okText="确定恢复"
            cancelText="取消"
            disabled={isDefault || saving}
          >
            <Button icon={<ReloadOutlined />} disabled={isDefault || saving}>
              恢复默认
            </Button>
          </Popconfirm>
          <Space>
            <Button onClick={onClose}>取消</Button>
            <Button type="primary" loading={saving} onClick={handleSave} disabled={!rules || loading}>
              保存
            </Button>
          </Space>
        </Space>
      }
    >
      {loading || !rules ? (
        <Skeleton active paragraph={{ rows: 8 }} />
      ) : (
        <>
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message="评级优先级：新词 → 高效 → 潜力 → 浪费 → 普通（命中即返）"
            description={
              <Paragraph style={{ marginBottom: 0, fontSize: 12 }}>
                "平均"指当前查询范围内按关键词数均摊的 CPC/曝光/花费。
                所有阈值都支持小数，CTR 写百分比（如 5 表示 5%）。
                {isDefault
                  ? ' 当前使用系统默认规则。'
                  : ' 当前使用自定义规则，"恢复默认"可删除。'}
              </Paragraph>
            }
          />

          {FIELDS.map(group => (
            <Card
              key={group.group}
              size="small"
              style={{ marginBottom: 10 }}
              title={
                <Space size={6}>
                  <span style={{ color: group.color }}>{group.icon}</span>
                  <Text strong>{group.label}</Text>
                  <Text type="secondary" style={{ fontWeight: 400, fontSize: 12 }}>
                    {group.desc}
                  </Text>
                </Space>
              }
            >
              <Row gutter={12}>
                {group.rows.map(f => {
                  const defaultVal = defaults?.[f.key]
                  return (
                    <Col span={12} key={f.key}>
                      <div style={{ fontSize: 12, color: '#666', marginBottom: 4 }}>{f.label}</div>
                      <InputNumber
                        size="small"
                        value={rules[f.key]}
                        onChange={v => setField(f.key, v)}
                        min={f.min}
                        max={f.max}
                        step={f.step}
                        addonAfter={f.suffix}
                        style={{ width: '100%' }}
                      />
                      {defaultVal !== undefined && (
                        <div style={{ fontSize: 11, color: '#bbb', marginTop: 2 }}>
                          默认 {defaultVal}
                        </div>
                      )}
                    </Col>
                  )
                })}
              </Row>
            </Card>
          ))}
        </>
      )}
    </Drawer>
  )
}
