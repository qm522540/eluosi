import { Space, Select, Button, Segmented, Input, InputNumber, Tooltip } from 'antd'
import { SyncOutlined, ThunderboltOutlined } from '@ant-design/icons'

const { Option } = Select

const PLATFORM_LABEL = { wb: 'WB', ozon: 'Ozon' }

const SeoFilterBar = ({
  shops, shopId, onShopChange,
  days, onDaysChange,
  roasThreshold, onRoasChange,
  source, onSourceChange,
  status, onStatusChange,
  keyword, onKeywordChange,
  onRefresh, refreshing,
  onReload,
}) => {
  return (
    <div style={{ marginBottom: 16 }}>
      <Space wrap size={[12, 12]}>
        <Select
          style={{ width: 220 }}
          placeholder="选择店铺"
          value={shopId}
          onChange={onShopChange}
          showSearch
          optionFilterProp="children"
        >
          {shops.map(s => (
            <Option key={s.id} value={s.id}>
              [{PLATFORM_LABEL[s.platform] || s.platform}] {s.name}
            </Option>
          ))}
        </Select>

        <Segmented
          value={days}
          onChange={onDaysChange}
          options={[
            { label: '7 天', value: 7 },
            { label: '14 天', value: 14 },
            { label: '30 天', value: 30 },
            { label: '60 天', value: 60 },
          ]}
        />

        <Tooltip title="只显示 ROAS ≥ 此值的付费词">
          <InputNumber
            addonBefore="ROAS ≥"
            min={0.1}
            max={100}
            step={0.5}
            value={roasThreshold}
            onChange={onRoasChange}
            style={{ width: 140 }}
          />
        </Tooltip>

        <Input.Search
          placeholder="搜索关键词"
          value={keyword}
          onChange={e => onKeywordChange(e.target.value)}
          onSearch={onReload}
          allowClear
          style={{ width: 200 }}
        />

        <Button
          type="primary"
          icon={<ThunderboltOutlined />}
          loading={refreshing}
          disabled={!shopId}
          onClick={onRefresh}
        >
          刷新引擎
        </Button>
        <Button icon={<SyncOutlined />} onClick={onReload} disabled={!shopId}>
          重新加载
        </Button>
      </Space>

      <div style={{ marginTop: 12 }}>
        <Space size="middle">
          <span style={{ color: '#999' }}>来源：</span>
          <Segmented
            value={source}
            onChange={onSourceChange}
            options={[
              { label: '全部', value: 'all' },
              { label: '付费·本商品', value: 'paid_self' },
              { label: '付费·类目', value: 'paid_category' },
              { label: '自然·本商品', value: 'organic_self' },
              { label: '自然·类目', value: 'organic_category' },
            ]}
          />
          <span style={{ color: '#999' }}>状态：</span>
          <Segmented
            value={status}
            onChange={onStatusChange}
            options={[
              { label: '待处理', value: 'pending' },
              { label: '已加入', value: 'adopted' },
              { label: '已忽略', value: 'ignored' },
              { label: '全部', value: 'all' },
            ]}
          />
        </Space>
      </div>
    </div>
  )
}

export default SeoFilterBar
