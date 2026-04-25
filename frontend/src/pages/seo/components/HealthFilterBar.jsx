import { Space, Select, Segmented, Input, Button } from 'antd'
import { SyncOutlined } from '@ant-design/icons'

const { Option } = Select

const PLATFORM_LABEL = { wb: 'WB', ozon: 'Ozon' }

const HealthFilterBar = ({
  shops, shopId, onShopChange,
  scoreRange, onScoreRangeChange,
  sort, onSortChange,
  keyword, onKeywordChange,
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

        <Input.Search
          placeholder="搜索商品名 / 俄语标题 / 本地编码"
          value={keyword}
          onChange={e => onKeywordChange(e.target.value)}
          onSearch={onReload}
          allowClear
          style={{ width: 280 }}
        />

        <Button icon={<SyncOutlined />} onClick={onReload} disabled={!shopId}>
          重新加载
        </Button>
      </Space>

      <div style={{ marginTop: 12 }}>
        <Space size="middle" wrap>
          <span style={{ color: '#999' }}>分档：</span>
          <Segmented
            value={scoreRange}
            onChange={onScoreRangeChange}
            options={[
              { label: '全部', value: 'all' },
              { label: '差 (< 40)', value: 'poor' },
              { label: '中 (40-70)', value: 'fair' },
              { label: '优 (≥ 70)', value: 'good' },
              { label: '无数据', value: 'data_insufficient' },
            ]}
          />
          <span style={{ color: '#999' }}>排序：</span>
          <Segmented
            value={sort}
            onChange={onSortChange}
            options={[
              { label: '最差在前', value: 'score_asc' },
              { label: '最优在前', value: 'score_desc' },
              { label: '缺词最多', value: 'gaps_desc' },
            ]}
          />
        </Space>
      </div>
    </div>
  )
}

export default HealthFilterBar
