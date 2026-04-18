# 关键词统计模块 API 接口规范

> 模块：Keyword Stats（广告关键词效果分析）
> 前缀：`/api/v1/keyword-stats`
> 平台范围：WB / Ozon
> 认证：Bearer Token + tenant_id 隔离
> 后端：老张
> 前端：小明
> 版本：v1（2026-04-17）

---

## 0. 业务背景

用户需要了解"广告预算花在了哪些搜索词上"，帮助优化关键词投放策略。

**数据来源**：
- WB：`GET /adv/v0/stats/keywords`（单次最多 7 天，需拆分请求）
- Ozon：`POST /api/client/statistics/phrases`（异步报告，无日期跨度限制）

**设计核心**：每天凌晨 Celery 增量拉取昨天数据存本地表，前端查本地表秒出。

---

## 1. 数据库表设计

### keyword_daily_stats

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK AUTO_INCREMENT | |
| tenant_id | BIGINT NOT NULL | 租户隔离 |
| shop_id | BIGINT NOT NULL | 店铺 |
| platform | ENUM('wb','ozon') | 平台 |
| campaign_id | BIGINT | 广告活动（本地 ad_campaigns.id） |
| platform_campaign_id | VARCHAR(100) | 平台活动 ID（冗余，方便排查） |
| keyword | VARCHAR(500) NOT NULL | 关键词文本 |
| sku | VARCHAR(100) | 商品 SKU（Ozon 有，WB 为空） |
| stat_date | DATE NOT NULL | 统计日期 |
| impressions | INT DEFAULT 0 | 曝光 |
| clicks | INT DEFAULT 0 | 点击 |
| spend | DECIMAL(12,2) DEFAULT 0 | 花费（卢布） |
| ctr | DECIMAL(8,4) DEFAULT 0 | 点击率（%） |
| cpc | DECIMAL(10,2) DEFAULT 0 | 单次点击成本（卢布） |
| created_at | DATETIME DEFAULT NOW() | |

**唯一键**：`UNIQUE(tenant_id, shop_id, campaign_id, keyword, sku, stat_date)`

**索引**：
- `idx_shop_date` → `(tenant_id, shop_id, stat_date)` —— 按店铺+日期范围查
- `idx_keyword` → `(tenant_id, shop_id, keyword(100))` —— 按关键词搜索

**数据保留**：90 天，Celery 每日清理过期数据。

---

## 2. Celery 定时任务

### 2.1 每日增量拉取

任务名：`sync_keyword_stats`
调度：每天莫斯科时间 03:00（`crontab(hour=0, minute=0)` UTC）

**WB 流程**：
```
遍历活跃 WB 店铺
  → 遍历该店铺活跃广告活动
  → GET /adv/v0/stats/keywords?advert_id=X&from=昨天&to=昨天
  → 解析响应 → upsert keyword_daily_stats
```

**Ozon 流程**：
```
遍历活跃 Ozon 店铺
  → 遍历该店铺活跃广告活动
  → POST /api/client/statistics/phrases（from=昨天 to=昨天）
  → 轮询报告状态 → 下载 CSV → 解析 → upsert keyword_daily_stats
```

### 2.2 首次初始化（手动触发）

接口：`POST /api/v1/keyword-stats/backfill`（见 §4.4）
- WB：回拉最近 90 天（拆 13 次 × 7 天请求）
- Ozon：回拉最近 90 天（一次请求）

---

## 3. 前端查询接口

### 3.1 关键词汇总列表

**GET** `/api/v1/keyword-stats/summary`

**查询参数**：

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| shop_id | int | 是 | | 店铺 ID |
| date_from | string | 否 | 7天前 | YYYY-MM-DD |
| date_to | string | 否 | 昨天 | YYYY-MM-DD |
| campaign_id | int | 否 | | 按活动筛选 |
| keyword | string | 否 | | 模糊搜索关键词 |
| sort_by | string | 否 | spend | spend / impressions / clicks / ctr / cpc |
| sort_order | string | 否 | desc | asc / desc |
| page | int | 否 | 1 | |
| size | int | 否 | 50 | 最大 200 |
| efficiency | string | 否 | | new / star / potential / waste / normal，按效能档位 server-side 过滤 |

**响应 data**：

```json
{
  "total": 128,
  "page": 1,
  "size": 50,
  "date_from": "2026-04-11",
  "date_to": "2026-04-17",
  "totals": {
    "keywords": 128,
    "impressions": 45230,
    "clicks": 1820,
    "spend": 12500.00,
    "avg_ctr": 4.02,
    "avg_cpc": 6.87
  },
  "items": [
    {
      "keyword": "серебряное кольцо",
      "impressions": 8230,
      "clicks": 412,
      "spend": 2150.00,
      "ctr": 5.01,
      "cpc": 5.22,
      "spend_pct": 17.2,
      "campaigns": [101, 102],
      "skus": ["123456", "789012"],
      "efficiency": "star"
    }
  ]
}
```

**`efficiency` 字段**（后端计算，前端展示标签）：

| 值 | 默认条件 | 含义 | 前端颜色 |
|---|---|---|---|
| `new` | 曝光 < `min_impressions`（默认 20） | 新词/观察中（数据不足，所有指标都不可信） | 青 |
| `star` | CTR ≥ `star_ctr_min`（默认5%）且 CPC ≤ 平均×`star_cpc_max_ratio`（默认1.0）| 高效词 | 绿 |
| `potential` | CTR ≥ `potential_ctr_min`（默认3%）且 曝光 ≤ 平均×`potential_impressions_max_ratio`（默认2.0）| 潜力词 | 蓝 |
| `waste` | CTR ≤ `waste_ctr_max`（默认1%）且 花费 ≥ 平均×`waste_spend_min_ratio`（默认1.0）| 浪费词 | 红 |
| `normal` | 以上都不符合 | 普通 | 灰 |

**优先级**：new → star → potential → waste → normal（命中即返，不会重复判定）

**可配置**：租户可通过 §3.7 / 3.8 / 3.9 接口自定义 7 项阈值；无自定义时走系统默认

**重要**：`efficiency` 是 SQL 后派生字段，server-side filter（`?efficiency=xxx`）走"先全量聚合 → Python 算 → filter → 切片分页"，所以 `total` 字段是 filter 后的真实数量，分页准确。

### 3.2 关键词 SKU 明细（Ozon 展开用）

**GET** `/api/v1/keyword-stats/sku-detail`

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| shop_id | int | 是 | |
| keyword | string | 是 | 精确匹配 |
| date_from | string | 否 | |
| date_to | string | 否 | |

**响应 data.items[]**：
```json
{
  "sku": "123456",
  "title": "银戒指套装",
  "impressions": 3200,
  "clicks": 180,
  "spend": 920.00,
  "ctr": 5.63,
  "cpc": 5.11
}
```

### 3.3 趋势数据（折线图用）

**GET** `/api/v1/keyword-stats/trend`

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| shop_id | int | 是 | |
| date_from | string | 否 | |
| date_to | string | 否 | |
| top | int | 否 | 默认 10，取花费 TOP N 的关键词 |
| metric | string | 否 | impressions / clicks / spend，默认 impressions |

**响应 data**：
```json
{
  "dates": ["2026-04-11", "2026-04-12", "..."],
  "series": [
    {
      "keyword": "серебряное кольцо",
      "values": [1200, 1350, 980, "..."]
    },
    {
      "keyword": "ожерелье женское",
      "values": [900, 1100, 870, "..."]
    }
  ]
}
```

### 3.4 历史数据回填（手动触发）

**POST** `/api/v1/keyword-stats/backfill`

```json
{ "shop_id": 1, "days": 90 }
```

**业务逻辑**：
- WB：拆成 `ceil(days/7)` 次请求，每次 7 天窗口
- Ozon：一次请求 from-to
- 异步执行（Celery task），前端 Loading 等完或轮询

**响应**：
```json
{
  "task_id": "celery-uuid-xxx",
  "msg": "回填任务已提交，WB 需约 13 次请求，预计 2-3 分钟"
}
```

### 3.5 否定关键词建议

**GET** `/api/v1/keyword-stats/negative-suggestions`

**查询参数**：shop_id, date_from, date_to

**逻辑**：在指定日期范围内，花费 > 0 但点击 < 3（或 CTR < 0.5%）的关键词，按花费降序。

**响应 data.items[]**：
```json
{
  "keyword": "кольцо обручальное",
  "impressions": 2500,
  "clicks": 2,
  "spend": 180.00,
  "ctr": 0.08,
  "reason": "花费 180₽ 仅 2 次点击，CTR 0.08%，建议设为否定关键词"
}
```

### 3.6 数据同步状态

**GET** `/api/v1/keyword-stats/sync-status`

**查询参数**：shop_id

**响应**：
```json
{
  "shop_id": 1,
  "platform": "wb",
  "last_sync_date": "2026-04-16",
  "total_days": 45,
  "earliest_date": "2026-03-03",
  "latest_date": "2026-04-16",
  "total_keywords": 342,
  "total_records": 8520
}
```

### 3.7 查询效能评级规则（租户级）

**GET** `/api/v1/keyword-stats/efficiency-rules`

**响应**：
```json
{
  "rules": {
    "min_impressions": 20,
    "star_ctr_min": 5.0,
    "star_cpc_max_ratio": 1.0,
    "potential_ctr_min": 3.0,
    "potential_impressions_max_ratio": 2.0,
    "waste_ctr_max": 1.0,
    "waste_spend_min_ratio": 1.0,
    "waste_min_days": 5
  },
  "defaults": { "... 同上系统默认值 ..." },
  "is_default": true
}
```

**字段二次复用说明**：
- `min_impressions` / `waste_ctr_max` / `waste_spend_min_ratio` / `waste_min_days` 同时被「**推广信息→活动详情→商品出价→屏蔽规则**」消费，判定"建议屏蔽"关键词。
- 用户在任一处修改阈值都立即影响两侧。

- `rules`：当前租户生效的规则（无自定义则等于 defaults）
- `defaults`：系统默认值，前端用作输入框的"默认"提示和"恢复默认"基准
- `is_default`：是否还在用默认值（用于灰掉"恢复默认"按钮）

### 3.8 保存效能评级规则

**PUT** `/api/v1/keyword-stats/efficiency-rules`

**请求体**（8 项全部可选，缺失字段后端用 DEFAULT 填补）：
```json
{
  "min_impressions": 30,
  "star_ctr_min": 7.0,
  "star_cpc_max_ratio": 0.9,
  "potential_ctr_min": 2.5,
  "potential_impressions_max_ratio": 1.2,
  "waste_ctr_max": 0.8,
  "waste_spend_min_ratio": 1.5,
  "waste_min_days": 5
}
```

**字段范围校验**：
- `min_impressions`：[0, 1000000]（整数次数）
- `waste_min_days`：[1, 90]（整数天数，屏蔽规则最低观察天数）
- 所有 `*_ctr_*` 字段：[0.0, 100.0]（百分比）
- 所有 `*_ratio*` 字段：[0.0, 10.0]（倍数）
- 越界返回 `code=10002` 错误

**响应**：同 §3.7 的结构，`is_default` 为 `false`

### 3.9 恢复默认规则

**POST** `/api/v1/keyword-stats/efficiency-rules/reset`

**行为**：从 `keyword_efficiency_rules` 表删除当前租户的行。下次查询自动走 `DEFAULT_RULES`。

**响应**：同 §3.7 结构，`rules=defaults`，`is_default=true`

---

## 4. 前端页面设计

### 4.1 入口

左侧菜单 → 数据报表（SubMenu）→ **关键词统计**，路径 `/reports/keywords`

### 4.2 布局

```
┌─ ① 筛选栏 ─────────────────────────────────────────────────────┐
│ [WB·Shario ▾]  [最近7天 | 近30天 | 按月▾]  [全部活动▾]  [查询]  │
│                                  数据截至 2026-04-16  共45天历史  │
└─────────────────────────────────────────────────────────────────┘

┌─ ② 汇总卡片 ───────────────────────────────────────────────────┐
│ 关键词数 128 | 总曝光 45,230 | 总点击 1,820 | CTR 4.02%         │
│ 总花费 12,500₽ | CPC 6.87₽                                     │
└─────────────────────────────────────────────────────────────────┘

┌─ ③ TOP 10 趋势图 ──────────────────────────────────────────────┐
│ ECharts 折线  [曝光 ○ | 点击 ○ | 花费 ●]                       │
└─────────────────────────────────────────────────────────────────┘

┌─ ④ 否定关键词建议 Alert ────────────────────────────────────────┐
│ ⚠ 发现 5 个浪费词：花费高但几乎无点击。点击查看                  │
└─────────────────────────────────────────────────────────────────┘

┌─ ⑤ 关键词明细表 ───────────────────────────────────────────────┐
│ 搜索 [🔍]  排序 [花费↓ ▾]                                      │
│ # | 关键词 | 效能 | 曝光 | 点击 | CTR | 花费 | CPC | 占比      │
│ 1 | серебряное кольцо | ⭐高效 | 8,230 | 412 | 5.0% | 2150₽ ...│
│   ▼ Ozon 展开 → SKU 级明细                                      │
│ 2 | ожерелье женское | 普通 | 6,100 | 298 | 4.9% | 1800₽ ...   │
│ 3 | кольцо обручальное | 🔴浪费 | 2,500 | 2 | 0.08% | 180₽ ... │
│                                              分页 + [导出Excel] │
└─────────────────────────────────────────────────────────────────┘
```

### 4.3 效能标签

```jsx
// star=绿色⭐ potential=蓝色💡 waste=红色🔴 normal=灰色
<Tag color="green">⭐ 高效词</Tag>
<Tag color="blue">💡 潜力词</Tag>
<Tag color="red">🔴 浪费词</Tag>
<Tag>普通</Tag>
```

---

## 5. 错误码

| code | 说明 |
|---|---|
| 0 | 成功 |
| 10002 | 参数错误 |
| 30001 | 店铺不存在 |
| 95001 | 关键词数据未初始化（该店铺从未同步过） |
| 95002 | 回填任务进行中 |

---

## 6. 版本历史

| 日期 | 版本 | 作者 | 变更 |
|---|---|---|---|
| 2026-04-17 | v1 | 小明 | 初稿 |
| 2026-04-17 | v1.1 | 老林 | 效能评级规则租户级自定义：迁移 041 + 3 个 endpoint（§3.7/3.8/3.9）+ 前端 EfficiencyRulesDrawer。§3.1 `efficiency` 字段说明改为参数化 |
| 2026-04-18 | v1.2 | 老林 | (1) 新增 `new` 档（曝光 < `min_impressions` 默认 20 的关键词，归"新词/观察中"）；(2) §3.1 加 `efficiency` query 参数 server-side filter 修复"客户端 sorter/filter + server 分页"互相冲突的"page 9 之后无数据但仍显示 39 页"bug；(3) `potential_impressions_max_ratio` 默认 1.0 → 2.0（v1.1 识别瑕疵：原默认潜力词命中率 0） |
| 2026-04-18 | v1.3 | 老林 | 新增 `waste_min_days`（默认 5）字段。`AdsOverview`「商品出价→屏蔽规则」复用本表 4 字段（`min_impressions` / `waste_ctr_max` / `waste_spend_min_ratio` / `waste_min_days`），废弃旧 localStorage rule1/rule2/rule3 |
