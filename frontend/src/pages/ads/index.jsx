import { useState, useEffect } from 'react'
import {
  Typography, Button, Space, Select, Tabs,
} from 'antd'
import {
  SearchOutlined,
} from '@ant-design/icons'
import { getShops } from '@/api/shops'
import { useAuthStore } from '@/stores/authStore'
import AdsOverview from './AdsOverview'
import AdsRules from './AdsRules'
import AdsAIPricing from './AdsAIPricing'
import ComingSoon from './ComingSoon'

const { Title } = Typography

const Ads = () => {
  const [searched, setSearched] = useState(false)
  const [mainTab, setMainTab] = useState('overview')

  // 筛选
  const [filterPlatform, setFilterPlatform] = useState(null)
  const [filterShopId, setFilterShopId] = useState(null)

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

  const canSearch = filterPlatform && filterShopId

  const handleSearch = () => {
    setSearched(true)
  }

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
            onChange={(v) => { setFilterPlatform(v); setFilterShopId(null); setSearched(false) }}
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
            onChange={(v) => { setFilterShopId(v); setSearched(false) }}
            disabled={!filterPlatform}
            options={shops.filter(s => s.platform === filterPlatform).map(s => ({ value: s.id, label: s.name }))}
          />
          <Button type="primary" icon={<SearchOutlined />} disabled={!canSearch} onClick={handleSearch}>确定</Button>
        </Space>
      </div>

      {/* 主功能Tab */}
      <Tabs activeKey={mainTab} onChange={setMainTab} items={[
        {
          key: 'overview',
          label: '概览',
          children: <AdsOverview shopId={filterShopId} platform={filterPlatform} shops={shops} searched={searched} />,
        },
        {
          key: 'rules',
          label: '自动化规则',
          children: <AdsRules shopId={filterShopId} platform={filterPlatform} searched={searched} />,
        },
        {
          key: 'ai-pricing',
          label: <Space size={4}><span>🤖</span><span>AI调价</span></Space>,
          children: <AdsAIPricing shopId={filterShopId} platform={filterPlatform} searched={searched} />,
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
      ]} />
    </div>
  )
}

export default Ads
