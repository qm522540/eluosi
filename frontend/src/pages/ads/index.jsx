import { useState, useEffect, useCallback } from 'react'
import {
  Typography, Button, Space, Select, Tabs, Tooltip, message,
} from 'antd'
import {
  SearchOutlined, SyncOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'
import { getShops } from '@/api/shops'
import { syncAdsByPlatform, getLastSyncTime } from '@/api/ads'
import { useAuthStore } from '@/stores/authStore'
import AdsOverview from './AdsOverview'
import AdsRules from './AdsRules'
import BidManagement from './BidManagement'
import ComingSoon from './ComingSoon'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

const { Title } = Typography

const Ads = () => {
  const [searched, setSearched] = useState(false)
  const [mainTab, setMainTab] = useState('overview')
  const [syncing, setSyncing] = useState(false)
  const [lastSyncTime, setLastSyncTime] = useState(null)

  // 筛选（下拉框当前值，随时变化）
  const [filterPlatform, setFilterPlatform] = useState(null)
  const [filterShopId, setFilterShopId] = useState(null)

  // 已确认的查询参数（只在点击"确定"时更新，驱动下方Tab内容）
  const [committedPlatform, setCommittedPlatform] = useState(null)
  const [committedShopId, setCommittedShopId] = useState(null)

  // 店铺列表
  const [shops, setShops] = useState([])

  // tenantId
  const tenant = useAuthStore(s => s.tenant)
  const tenantId = tenant?.id

  useEffect(() => {
    getShops({ page: 1, page_size: 100 }).then(res => {
      setShops(res.data.items || [])
    }).catch(() => {})
  }, [])

  // 已确认店铺后获取上次同步时间
  useEffect(() => {
    if (committedShopId) {
      getLastSyncTime(committedShopId).then(res => {
        if (res.data?.last_sync_at) {
          setLastSyncTime(new Date(res.data.last_sync_at))
        } else {
          setLastSyncTime(null)
        }
      }).catch(() => {})
    } else {
      setLastSyncTime(null)
    }
  }, [committedShopId])

  const canSearch = filterPlatform && filterShopId

  const handleSearch = () => {
    setCommittedPlatform(filterPlatform)
    setCommittedShopId(filterShopId)
    setSearched(true)
  }

  // 刷新当前Tab数据：通过切换searched状态触发子组件重新加载
  const refreshCurrentTab = useCallback(() => {
    setSearched(false)
    setTimeout(() => setSearched(true), 0)
  }, [])

  const handleSync = async () => {
    if (!committedPlatform) return
    setSyncing(true)
    try {
      await syncAdsByPlatform(committedPlatform)
      setLastSyncTime(new Date())
      message.success('同步任务已提交，数据将在后台更新')
      if (searched) {
        refreshCurrentTab()
      }
    } catch {
      message.error('同步失败，请稍后重试')
    } finally {
      setSyncing(false)
    }
  }

  // Tab栏右侧额外内容：同步按钮（跟随已确认的店铺）
  const tabBarExtra = (committedPlatform && committedShopId) ? (
    <Space size={8} style={{ paddingRight: 4, alignItems: 'center' }}>
      {lastSyncTime && !syncing && (
        <span style={{ fontSize: 12, color: 'var(--color-text-secondary, #999)', whiteSpace: 'nowrap' }}>
          {dayjs(lastSyncTime).fromNow()}同步
        </span>
      )}
      <Tooltip
        title={
          lastSyncTime
            ? `上次同步：${dayjs(lastSyncTime).format('MM-DD HH:mm')}`
            : '从平台拉取最新活动列表和状态'
        }
        placement="bottomRight"
      >
        <Button
          size="small"
          icon={<SyncOutlined spin={syncing} />}
          onClick={handleSync}
          loading={syncing}
          style={{
            fontSize: 13,
            color: 'var(--color-text-secondary, #999)',
            border: '1px solid var(--color-border-tertiary, #e8e8e8)',
            background: 'transparent',
          }}
        >
          {syncing ? '同步中' : '同步数据'}
        </Button>
      </Tooltip>
    </Space>
  ) : null

  return (
    <div>
      {/* 顶部操作栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0 }}>广告管理</Title>
        <Space>
          <Select
            placeholder="选择平台"
            allowClear
            style={{ width: 150 }}
            value={filterPlatform}
            onChange={(v) => { setFilterPlatform(v); setFilterShopId(null) }}
            options={[
              { value: 'wb', label: 'Wildberries' },
              { value: 'ozon', label: 'Ozon' },
              { value: 'yandex', label: 'Yandex Market' },
            ]}
          />
          <Select
            placeholder="选择店铺"
            allowClear
            style={{ width: 160 }}
            value={filterShopId}
            onChange={(v) => setFilterShopId(v)}
            disabled={!filterPlatform}
            options={shops.filter(s => s.platform === filterPlatform).map(s => ({ value: s.id, label: s.name }))}
          />
          <Button type="primary" icon={<SearchOutlined />} disabled={!canSearch} onClick={handleSearch}>确定</Button>
        </Space>
      </div>

      {/* 主功能Tab */}
      <Tabs
        activeKey={mainTab}
        onChange={setMainTab}
        tabBarExtraContent={{ right: tabBarExtra }}
        items={[
          {
            key: 'overview',
            label: '概览',
            children: <AdsOverview shopId={committedShopId} platform={committedPlatform} shops={shops} searched={searched} />,
          },
          {
            key: 'rules',
            label: '自动化规则',
            children: <AdsRules shopId={committedShopId} platform={committedPlatform} searched={searched} />,
          },
          {
            key: 'bid-management',
            label: <Space size={4}><span>💰</span><span>出价管理</span></Space>,
            children: <BidManagement shopId={committedShopId} platform={committedPlatform} tenantId={tenantId} />,
          },
          {
            key: 'analysis',
            label: '数据分析',
            children: <ComingSoon title="数据分析" />,
          },
          {
            key: 'budget',
            label: '预算管理',
            children: <ComingSoon title="预算管理" />,
          },
        ]}
      />
    </div>
  )
}

export default Ads
