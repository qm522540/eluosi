import { useState, useEffect } from 'react'
import {
  Typography, Button, Space, Select, Tabs,
} from 'antd'
import {
  SearchOutlined, SyncOutlined, SettingOutlined,
  FundOutlined, BarChartOutlined, RobotOutlined, WalletOutlined,
} from '@ant-design/icons'
import { getShops } from '@/api/shops'
import { AD_STATUS } from '@/utils/constants'
import AdsOverview from './AdsOverview'
import AdsAnalysis from './AdsAnalysis'
import AdsRules from './AdsRules'
import AdsBudget from './AdsBudget'
import AdsAIPricing from './AdsAIPricing'

const { Title } = Typography

const Ads = () => {
  const [searched, setSearched] = useState(false)
  const [mainTab, setMainTab] = useState('overview')

  // 筛选
  const [filterPlatform, setFilterPlatform] = useState(null)
  const [filterShopId, setFilterShopId] = useState(null)

  // 店铺列表
  const [shops, setShops] = useState([])

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
          label: <span><FundOutlined /> 概览</span>,
          children: <AdsOverview shopId={filterShopId} platform={filterPlatform} shops={shops} searched={searched} />,
        },
        {
          key: 'analysis',
          label: <span><BarChartOutlined /> 数据分析</span>,
          children: <AdsAnalysis shopId={filterShopId} platform={filterPlatform} searched={searched} />,
        },
        {
          key: 'rules',
          label: <span><RobotOutlined /> 自动化规则</span>,
          children: <AdsRules shopId={filterShopId} platform={filterPlatform} searched={searched} />,
        },
        {
          key: 'budget',
          label: <span><WalletOutlined /> 预算管理</span>,
          children: <AdsBudget shopId={filterShopId} platform={filterPlatform} searched={searched} />,
        },
        {
          key: 'ai-pricing',
          label: <span>🤖 AI调价</span>,
          children: <AdsAIPricing shopId={filterShopId} platform={filterPlatform} searched={searched} />,
        },
      ]} />
    </div>
  )
}

export default Ads
