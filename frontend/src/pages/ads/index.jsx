import { useState, useEffect, useCallback } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
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
import { getLastSyncTime } from '@/api/ads'
import { syncData } from '@/api/bid_management'
import { useAuthStore } from '@/stores/authStore'
import AdsOverview from './AdsOverview'
import AdsRules from './AdsRules'
import BidManagement from './BidManagement'
import ComingSoon from './ComingSoon'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

const { Title } = Typography

// 左侧菜单的"推广信息 / 出价管理"两项通过 URL 反推 mainTab
// 其他 Tab（规则/数据分析/预算）不在菜单里，点击后 URL 回落到 /ads 维持"推广信息"高亮
const PATH_TO_TAB = {
  '/ads': 'overview',
  '/ads/bid-management': 'bid-management',
}
const TAB_TO_PATH = {
  overview: '/ads',
  'bid-management': '/ads/bid-management',
}

const Ads = () => {
  const location = useLocation()
  const navigate = useNavigate()

  const [searched, setSearched] = useState(false)
  const [mainTab, setMainTab] = useState(PATH_TO_TAB[location.pathname] || 'overview')
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

  // URL 变化（左侧菜单点击）时同步 Tab
  useEffect(() => {
    const tab = PATH_TO_TAB[location.pathname]
    if (tab && tab !== mainTab) setMainTab(tab)
  }, [location.pathname])

  // Tab 切换时回写 URL（仅两个有菜单入口的 Tab 改变 URL，其他回落到 /ads）
  const handleTabChange = (newTab) => {
    setMainTab(newTab)
    const targetPath = TAB_TO_PATH[newTab] || '/ads'
    if (targetPath !== location.pathname) navigate(targetPath, { replace: true })
  }

  // 已确认店铺后获取上次同步时间，超过30分钟自动同步
  // 仅"广告概览" Tab 下触发，其他 Tab（规则/出价管理/数据分析/预算）不自动同步
  useEffect(() => {
    const needAutoSync = mainTab === 'overview'
    if (committedShopId && committedPlatform && needAutoSync) {
      getLastSyncTime(committedShopId).then(res => {
        if (res.data?.last_sync_at) {
          const syncTime = new Date(res.data.last_sync_at)
          setLastSyncTime(syncTime)
          const diffMin = (Date.now() - syncTime.getTime()) / 60000
          if (diffMin > 30) {
            setSyncing(true)
            syncData(committedShopId).then(() => {
              setLastSyncTime(new Date())
              message.info('数据已超过30分钟，已自动同步')
              if (searched) refreshCurrentTab()
            }).catch(() => {}).finally(() => setSyncing(false))
          }
        } else {
          setLastSyncTime(null)
          setSyncing(true)
          syncData(committedShopId).then(() => {
            setLastSyncTime(new Date())
            message.info('首次进入，已自动同步数据')
            if (searched) refreshCurrentTab()
          }).catch(() => {}).finally(() => setSyncing(false))
        }
      }).catch(() => {})
    } else if (!committedShopId) {
      setLastSyncTime(null)
    }
  }, [committedShopId, committedPlatform, mainTab])

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
    if (!committedShopId) return
    setSyncing(true)
    try {
      await syncData(committedShopId)
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

  const tabBarExtra = null

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
        onChange={handleTabChange}
        tabBarExtraContent={{ right: tabBarExtra }}
        items={[
          {
            key: 'overview',
            label: '概览',
            children: <AdsOverview shopId={committedShopId} platform={committedPlatform} shops={shops} searched={searched} syncing={syncing} lastSyncTime={lastSyncTime} onSync={handleSync} />,
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
