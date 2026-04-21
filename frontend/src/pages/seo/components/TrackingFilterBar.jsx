import { Row, Col, Select, Segmented, Input, InputNumber, Switch, Space, Button, Tooltip } from 'antd'
import { ReloadOutlined, WarningOutlined } from '@ant-design/icons'

const { Option } = Select

const DATE_RANGE_OPTS = [
  { label: '最近 7 天', value: 7 },
  { label: '最近 14 天', value: 14 },
  { label: '最近 30 天', value: 30 },
]

const SORT_OPTS = [
  { label: '本期曝光 ↓', value: 'impressions_desc' },
  { label: '本期订单 ↓', value: 'orders_desc' },
  { label: '跌幅最大 ↓', value: 'drop_desc' },
  { label: '新增词 优先', value: 'new_desc' },
]

const TrackingFilterBar = ({
  shops, shopId, onShopChange,
  dateRange, onDateRangeChange,
  sort, onSortChange,
  keyword, onKeywordChange,
  minImpressions, onMinImpressionsChange,
  alertOnly, onAlertOnlyChange,
  onReload,
}) => (
  <div style={{ marginBottom: 12 }}>
    <Row gutter={[8, 8]} align="middle">
      <Col>
        <Select
          value={shopId}
          onChange={onShopChange}
          style={{ width: 220 }}
          placeholder="选店铺"
          showSearch
          optionFilterProp="children"
        >
          {shops.map((s) => (
            <Option key={s.id} value={s.id}>
              [{s.platform.toUpperCase()}] {s.name}
            </Option>
          ))}
        </Select>
      </Col>
      <Col>
        <Segmented options={DATE_RANGE_OPTS} value={dateRange} onChange={onDateRangeChange} />
      </Col>
      <Col>
        <Select value={sort} onChange={onSortChange} style={{ width: 150 }}>
          {SORT_OPTS.map((o) => <Option key={o.value} value={o.value}>{o.label}</Option>)}
        </Select>
      </Col>
      <Col flex="auto">
        <Input.Search
          allowClear
          placeholder="搜索核心词（俄语）"
          value={keyword}
          onChange={(e) => onKeywordChange(e.target.value)}
          onSearch={onReload}
          style={{ maxWidth: 300 }}
        />
      </Col>
      <Col>
        <Space size={4}>
          <Tooltip title="过滤低曝光噪声 — 本期或上期曝光 ≥ 此值才展示">
            <span style={{ fontSize: 12, color: '#666' }}>最低曝光</span>
          </Tooltip>
          <InputNumber
            min={0}
            max={9999}
            value={minImpressions}
            onChange={onMinImpressionsChange}
            style={{ width: 80 }}
          />
        </Space>
      </Col>
      <Col>
        <Space size={4}>
          <WarningOutlined style={{ color: '#fa8c16' }} />
          <span style={{ fontSize: 12 }}>仅看预警</span>
          <Switch size="small" checked={alertOnly} onChange={onAlertOnlyChange} />
        </Space>
      </Col>
      <Col>
        <Button icon={<ReloadOutlined />} onClick={onReload}>刷新</Button>
      </Col>
    </Row>
  </div>
)

export default TrackingFilterBar
