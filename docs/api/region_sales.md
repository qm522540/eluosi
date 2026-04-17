# 地区销售分析模块 API 接口规范

> 模块：Region Sales（地区销售排行 + 趋势对比）
> 前缀：`/api/v1/region-stats`
> 平台：WB / Ozon
> 后端：老张
> 前端：小明
> 版本：v1（2026-04-17）

---

## 0. 业务背景

卖家想知道"哪个城市/地区买我的东西最多"，辅助库存分配和投放策略。

**数据来源**：
- WB：`POST /api/v1/analytics/region-sale`（最多 31 天/次）
- Ozon：`POST /v1/analytics/data`（dimension=`region`，Premium 完整数据）

**注意**：广告花费无地区拆分，所以本模块只做**销售维度**（订单数 / 销售额 / 客单价），不涉及地区级 ROAS。

---

## 1. 数据库表

### region_daily_stats

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | |
| tenant_id | BIGINT NOT NULL | |
| shop_id | BIGINT NOT NULL | |
| platform | ENUM('wb','ozon') | |
| region_name | VARCHAR(200) NOT NULL | 地区名（俄文原文） |
| stat_date | DATE NOT NULL | |
| orders | INT DEFAULT 0 | 订单数 |
| revenue | DECIMAL(14,2) DEFAULT 0 | 销售额（卢布） |
| returns | INT DEFAULT 0 | 退货数（WB 有，Ozon 可能没有） |
| created_at | DATETIME DEFAULT NOW() | |

**唯一键**：`UNIQUE(tenant_id, shop_id, region_name, stat_date)`

保留 90 天。

---

## 2. Celery 定时任务

任务名：`sync_region_stats`
调度：每天莫斯科时间 04:00

- WB：`POST /api/v1/analytics/region-sale`，from=昨天 to=昨天
- Ozon：`POST /v1/analytics/data`，dimension=region，date_from=昨天 date_to=昨天

首次回填：同关键词模块，手动触发回填 90 天。

---

## 3. 前端查询接口

### 3.1 地区排行

**GET** `/api/v1/region-stats/ranking`

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| shop_id | int | 是 | | |
| date_from | string | 否 | 7天前 | YYYY-MM-DD |
| date_to | string | 否 | 昨天 | |
| sort_by | string | 否 | revenue | revenue / orders / avg_price / returns |
| limit | int | 否 | 50 | |

**响应 data**：
```json
{
  "date_from": "2026-04-11",
  "date_to": "2026-04-17",
  "totals": {
    "regions": 45,
    "orders": 520,
    "revenue": 285000.00,
    "avg_price": 548.08
  },
  "items": [
    {
      "region_name": "Москва",
      "region_name_zh": "莫斯科",
      "orders": 100,
      "revenue": 50000.00,
      "avg_price": 500.00,
      "returns": 5,
      "return_rate": 5.0,
      "orders_pct": 19.2,
      "revenue_pct": 17.5
    }
  ]
}
```

### 3.2 地区趋势（折线图用）

**GET** `/api/v1/region-stats/trend`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| shop_id | int | 是 | |
| date_from | string | 否 | |
| date_to | string | 否 | |
| top | int | 否 | 默认 5 |
| metric | string | 否 | orders / revenue，默认 orders |

**响应 data**：
```json
{
  "dates": ["2026-04-11", "2026-04-12"],
  "series": [
    { "region_name": "Москва", "values": [15, 18] },
    { "region_name": "Санкт-Петербург", "values": [8, 10] }
  ]
}
```

### 3.3 回填历史

**POST** `/api/v1/region-stats/backfill`
```json
{ "shop_id": 1, "days": 90 }
```

### 3.4 同步状态

**GET** `/api/v1/region-stats/sync-status?shop_id=1`

---

## 4. 版本历史

| 日期 | 版本 | 作者 | 变更 |
|---|---|---|---|
| 2026-04-17 | v1 | 小明 | 初稿 |
