import { useState, useEffect, useCallback } from 'react'
import { useLocation } from 'react-router-dom'
import {
  Typography, Button, Space, Select, message,
} from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'
import { getShops } from '@/api/shops'
import { getLastSyncTime } from '@/api/ads'
import { syncData } from '@/api/bid_management'
import { useAuthStore } from '@/stores/authStore'
import AdsOverview from './AdsOverview'
import BidManagement from './BidManagement'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

const { Title } = Typography
const { Option } = Select

// 平台配色（与 Products.jsx 保持一致的视觉语言）
const PLATFORM_COLOR = {
  wb: { label: 'WB' },
  ozon: { label: 'Ozon' },
  yandex: { label: 'YM' },
}

const Ads = () => {
  const location = useLocation()
  const isBidMgmt = location.pathname === '/ads/bid-management'
  const pageTitle = isBidMgmt ? '出价管理' : '推广信息'

  const [searched, setSearched] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [lastSyncTime, setLastSyncTime] = useState(null)

  // 合并为单选：shop_id 带出 platform（从 Option 的 platform 属性取）
  const [filterShopId, setFilterShopId] = useState(null)
  const [filterPlatform, setFilterPlatform] = useState(null)

  const [committedShopId, setCommittedShopId] = useState(null)
  const [committedPlatform, setCommittedPlatform] = useState(null)

  const [shops, setShops] = useState([])

  const tenant = useAuthStore(s => s.tenant)
  const tenantId = tenant?.id

  useEffect(() => {
    getShops({ page: 1, page_size: 100 }).then(res => {
      setShops(res.data.items || [])
    }).catch(() => {})
  }, [])

  // "推广信息"页：有数据则检查 30 分钟自动同步
  // "出价管理"页：不自动同步（走自己的 bid-management 调度）
  useEffect(() => {
    if (isBidMgmt) return
    if (committedShopId && committedPlatform) {
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
  }, [committedShopId, committedPlatform, isBidMgmt])

  const canSearch = !!filterShopId

  const handleSearch = () => {
    setCommittedShopId(filterShopId)
    setCommittedPlatform(filterPlatform)
    setSearched(true)
  }

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
      if (searched) refreshCurrentTab()
    } catch {
      message.error('同步失败，请稍后重试')
    } finally {
      setSyncing(false)
    }
  }

  return (
    <div>
      {/* 顶部操作栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0 }}>{pageTitle}</Title>
        <Space>
          <Select
            style={{ width: 260 }}
            value={filterShopId}
            onChange={(shopId, opt) => {
              setFilterShopId(shopId ?? null)
              setFilterPlatform(opt?.platform || null)
            }}
            placeholder="选择平台 · 店铺"
            allowClear
            showSearch
            optionFilterProp="children"
          >
            {['wb', 'ozon', 'yandex'].map(plat => {
              const list = shops.filter(s => s.platform === plat)
              if (!list.length) return null
              const cfg = PLATFORM_COLOR[plat] || { label: plat }
              return (
                <Select.OptGroup key={plat} label={cfg.label}>
                  {list.map(s => (
                    <Option key={s.id} value={s.id} platform={plat}>
                      {cfg.label} · {s.name}
                    </Option>
                  ))}
                </Select.OptGroup>
              )
            })}
          </Select>
          <Button type="primary" icon={<SearchOutlined />} disabled={!canSearch} onClick={handleSearch}>
            确定
          </Button>
        </Space>
      </div>

      {isBidMgmt ? (
        <BidManagement
          shopId={committedShopId}
          platform={committedPlatform}
          tenantId={tenantId}
        />
      ) : (
        <AdsOverview
          shopId={committedShopId}
          platform={committedPlatform}
          shops={shops}
          searched={searched}
          syncing={syncing}
          lastSyncTime={lastSyncTime}
          onSync={handleSync}
        />
      )}
    </div>
  )
}

export default Ads
