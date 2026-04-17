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

## 4. 决策扩展字段（v2，2026-04-17 老张）

### 4.1 ranking 接口扩展

items 每条新增：
| 字段 | 类型 | 说明 |
|---|---|---|
| net_profit_est | number | 估算净贡献（₽）= 销售额 × 店铺平均毛利率 − 退货损失 |
| suggestion | enum | `block` / `watch` / `keep` |
| suggestion_reason | string | 中文理由（用户 Tooltip 显示） |

totals 新增：
| 字段 | 说明 |
|---|---|
| avg_margin_pct | 店铺平均毛利率（%） |
| margin_source | 毛利率来源说明（products 平均 / AI 配置 / 兜底） |
| net_profit_est | 全店净贡献 |

### 4.2 建议规则

```
if orders < 3:              keep  (样本不足)
elif return_rate >= 15%:    block (退货率过高)
elif net_profit_est < 0:    block (亏钱)
elif return_rate >= 8%:     watch (退货率偏高)
elif revenue_pct<1 and orders<10: watch (规模过低)
else:                        keep
```

### 4.3 毛利率来源优先级

1. 该店铺 products.net_margin 非空值的算术平均
2. ai_pricing_configs.default_config.gross_margin
3. 兜底 0.30（30%）

---

## 5. 地区投放决策说明（必读）

### 5.1 广告层无法按地区排除投放

**调研结论（2026-04-17）**：

| 平台 | 广告类型 | 地区定向 | 地区排除 | 备注 |
|---|---|---|---|---|
| WB | АРК（自动）| ❌ | ❌ | 算法黑盒 |
| WB | Auction（搜索/轮播 CPM）| ❌ | ❌ | OpenAPI `/adv/v*` 无地区字段 |
| WB | WB.Медиа（横幅 CPM）| ✅（仅定向）| ❌ | 只能选投放区域，不能排除 |
| Ozon | Трафареты | ❌ | ❌ | Performance API 无地区参数 |
| Ozon | Продвижение в поиске | ❌ | ❌ | 同上 |
| Ozon | Медийная реклама | ✅（仅定向）| ❌ | 只能选投放区域 |

**结论**：**两个平台的主流效果广告都无法排除特定地区的投放**。

### 5.2 唯一硬阻断办法：物流层

- **WB**：关闭该地区仓储 coverage（склад → регионы）
- **Ozon**：商品卡关闭 доставка в регион

广告触达无法阻止，但**订单无法成交**（用户下不了单），等效于屏蔽。

### 5.3 Ozon Premium Plus（订单归因）价值评估

- **可用场景**：事后分析哪些地区亏损 → 下架该地区商品
- **不可用场景**：前置阻断广告投放（平台不支持）
- **当前结论**：若核心动作还是"物流侧下架"，则本模块 v2 的 suggestion 字段 + 店铺后台物流配置 **已足够支持决策**，Ozon Premium Plus 暂不值得升级

### 5.4 业务建议路径

```
地区销售排行 (本模块)
   ↓ 识别
[建议屏蔽] 标签的地区
   ↓ 人工操作
WB: 关闭该地区仓储 coverage
Ozon: 商品卡关闭 доставка в регион
   ↓ 结果
该地区下单率降至零，等效广告预算节省
```

**参考链接**：
- [Wildberries 广告 OpenAPI](https://openapi.wildberries.ru/promotion/api/ru/)
- [Ozon Performance 平台文档](https://docs.ozon.ru/performance/)
- [WB АРК 不可控定向讨论](https://vc.ru/marketplace/2178731-avtomaticheskaya-reklamnaya-kampaniya-na-wildberries)

---

## 6. 版本历史

| 日期 | 版本 | 作者 | 变更 |
|---|---|---|---|
| 2026-04-17 | v1 | 小明 | 初稿 |
| 2026-04-17 | v2 | 老张 | 加净贡献估算 + 屏蔽建议 + 广告地区排除能力调研结论 |
