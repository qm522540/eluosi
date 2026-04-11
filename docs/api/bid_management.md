# 出价管理模块 API 接口规范

> 模块：Bid Management（分时调价 + AI调价 统一入口）
> 前缀：`/api/v1/bid-management`
> 平台范围：**本期仅支持 Ozon**；WB/Yandex 后续扩展
> 认证：所有接口需携带 `Authorization: Bearer <token>`
> 多租户隔离：所有查询/写入必须带上 JWT 解出的 `tenant_id` 过滤，禁止跨租户访问
> 架构师：老林
> 版本：v1（2026-04-11）

---

## 0. 通用约定

### 0.1 统一响应格式

```json
{
  "code": 0,
  "msg": "success",
  "data": {},
  "timestamp": 1744300800
}
```

成功 `code=0`，其余为错误码（见 §8）。失败时 `data=null`。

### 0.2 时间字段统一规范

- **存储**：MySQL `DATETIME` 存UTC时间
- **返回**：ISO 8601 格式字符串，如 `2026-04-11T08:30:00Z`（UTC）
- **"莫斯科时间"字段**：仅在面向用户展示的字段（如 `moscow_time` / `moscow_hour`）使用，值必须明确标注为莫斯科时区
- 莫斯科 = UTC+3（无夏令时，俄罗斯自2014年起固定）

### 0.3 金额字段规范

- 所有金额字段单位：**卢布（RUB）**，`DECIMAL(10,2)`
- 后端调用 Ozon API 时再做纳卢布换算（×1000000），业务层和 API 层全部用卢布

### 0.4 店铺作用域强制规则

> **重要**：所有手动触发类接口（analyze/enable/disable/data-sync/...）**必须**按 `shop_id` 过滤，禁止全租户批处理。定时任务另走 Celery Beat 路径，不走本 API。

### 0.5 分页参数约定

- `page`：默认 1，最小 1
- `size`：默认 20，最大 100
- 返回字段：`total` / `page` / `size` / `items`

---

## 1. 状态栏（Dashboard）

用于前端页面顶部实时展示当前执行状态。

### 1.1 获取店铺出价管理状态

**GET** `/api/v1/bid-management/dashboard/{shop_id}`

**响应 data**：

```json
{
  "shop_id": 1,
  "moscow_time": "2026-04-11T15:07:32+03:00",
  "moscow_hour": 15,
  "current_period": "mid",
  "current_period_name": "次高峰期",
  "current_ratio": 100,
  "next_execute_at": "16:05",
  "next_execute_minutes": 58,
  "last_executed_at": "2026-04-11T15:05:12+03:00",
  "last_execute_result": "调整12个SKU",
  "last_execute_status": "success",
  "active_mode": "time_pricing"
}
```

**字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| moscow_time | string | 莫斯科当前时间（ISO 8601 带时区） |
| moscow_hour | int | 莫斯科小时 0-23 |
| current_period | enum | peak / mid / low / none（none=未开启任何模式） |
| current_period_name | string | 中文展示名 |
| current_ratio | int | 当前系数（%），AI模式时为 null |
| next_execute_at | string | "HH:MM" 格式，下次 Celery 执行点（每小时05分） |
| next_execute_minutes | int | 距离下次执行的分钟数 |
| last_executed_at | string\|null | 上次执行时间，ISO 8601 带时区 |
| last_execute_result | string\|null | 结果摘要（如 "调整12个SKU" / "3个建议生成"） |
| last_execute_status | enum | success / failed / partial / none |
| active_mode | enum | time_pricing / ai / none（两者互斥） |

**错误码**：`30001`（店铺不存在）

---

## 2. 分时调价（Time Pricing）

### 2.1 获取分时调价规则

**GET** `/api/v1/bid-management/time-pricing/{shop_id}`

**响应 data**：

```json
{
  "shop_id": 1,
  "is_active": false,
  "peak_hours": [10, 11, 12, 13, 19, 20, 21, 22],
  "peak_ratio": 120,
  "mid_hours": [7, 8, 9, 14, 15, 16, 17, 18],
  "mid_ratio": 100,
  "low_hours": [0, 1, 2, 3, 4, 5, 6, 23],
  "low_ratio": 60,
  "last_executed_at": null,
  "last_execute_result": null,
  "updated_at": "2026-04-11T12:00:00Z"
}
```

**错误码**：`92001`

### 2.2 更新分时调价规则

**PUT** `/api/v1/bid-management/time-pricing/{shop_id}`

**请求体**：

```json
{
  "peak_hours": [10, 11, 12, 13, 19, 20, 21, 22],
  "mid_hours":  [7, 8, 9, 14, 15, 16, 17, 18],
  "low_hours":  [0, 1, 2, 3, 4, 5, 6, 23],
  "peak_ratio": 130,
  "mid_ratio":  100,
  "low_ratio":  50
}
```

**校验规则**：

- `peak_hours ∪ mid_hours ∪ low_hours == {0..23}`（24小时必须全覆盖）
- 三个数组**两两不相交**（任一小时只能属于一档）
- 每个小时取值范围 `[0, 23]`，整数
- `peak_ratio / mid_ratio / low_ratio` 范围 `[10, 500]`
- 推荐约束：`low_ratio ≤ mid_ratio ≤ peak_ratio`（非强制，仅给前端警告）

**响应 data**：返回更新后的完整对象（同 §2.1）

**错误码**：`92001`、`92007`、`92008`、`10002`

### 2.3 启用分时调价

**POST** `/api/v1/bid-management/time-pricing/{shop_id}/enable`

**业务规则**：
- 启用前**必须**调用 `/conflict-check` 或后端自校验：若 AI 调价已启用则返回 `92003`
- 启用成功后，下次 Celery Beat 时（每小时05分）开始执行
- 启用瞬间**不执行**调价，等下次beat tick

**响应 data**：

```json
{
  "shop_id": 1,
  "is_active": true,
  "next_execute_at": "16:05"
}
```

**错误码**：`92001`、`92003`、`92009`（数据未初始化）

### 2.4 停用分时调价

**POST** `/api/v1/bid-management/time-pricing/{shop_id}/disable`

**业务规则**：
- 停用后不会自动恢复已被调整的出价；若用户需要恢复出价到 `original_bid`，走 §2.5 `restore-sku`

**响应 data**：

```json
{ "shop_id": 1, "is_active": false }
```

### 2.5 单SKU恢复出价

**POST** `/api/v1/bid-management/time-pricing/{shop_id}/restore-sku`

**请求体**：

```json
{ "platform_sku_id": "123456789" }
```

**业务逻辑**：
- 读取 `ad_groups.original_bid`，调用 Ozon API 把出价改回 `original_bid`
- 写 `bid_adjustment_logs`，`execute_type='user_manual'`
- 不清空 `original_bid`（便于再次参考）

**响应 data**：

```json
{
  "platform_sku_id": "123456789",
  "sku_name": "银色项链套装",
  "restored_bid": 50.00,
  "previous_bid": 65.00
}
```

**错误码**：`92001`、`40003`（listing/ad_group 不存在）、`92011`

### 2.6 分时调价当前SKU执行状态

**GET** `/api/v1/bid-management/time-pricing/{shop_id}/status`

返回当前店铺下所有参与分时调价的 SKU 执行状态，按**广告活动分组**，供前端展示"当前各SKU出价情况"。

**查询参数**：

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| campaign_id | int | 无 | 仅返回指定活动 |
| keyword | string | 无 | 活动名/SKU名模糊搜索 |

**响应 data**：

```json
{
  "campaigns": [
    {
      "campaign_id": 101,
      "campaign_name": "2026春季饰品推广",
      "skus": [
        {
          "platform_sku_id": "123456789",
          "sku_name": "银色项链套装",
          "original_bid": 50.00,
          "current_bid": 60.00,
          "last_auto_bid": 60.00,
          "period": "mid",
          "ratio": 120,
          "user_managed": false,
          "last_adjusted_at": "2026-04-11T14:05:12Z"
        }
      ]
    }
  ]
}
```

---

## 3. AI调价（AI Pricing）

### 3.1 获取AI调价配置

**GET** `/api/v1/bid-management/ai-pricing/{shop_id}`

**响应 data**：

```json
{
  "shop_id": 1,
  "is_active": false,
  "auto_execute": false,
  "template_name": "default",
  "conservative_config": {
    "target_roas": 2.0, "min_roas": 1.5,
    "max_bid": 100, "daily_budget": 500,
    "max_adjust_pct": 15, "gross_margin": 0.5
  },
  "default_config": {
    "target_roas": 3.0, "min_roas": 1.8,
    "max_bid": 180, "daily_budget": 2000,
    "max_adjust_pct": 30, "gross_margin": 0.5
  },
  "aggressive_config": {
    "target_roas": 4.0, "min_roas": 2.5,
    "max_bid": 300, "daily_budget": 0,
    "max_adjust_pct": 25, "gross_margin": 0.5
  },
  "last_executed_at": null,
  "last_execute_status": null,
  "last_error_msg": null,
  "retry_at": null
}
```

### 3.2 更新AI调价配置

**PUT** `/api/v1/bid-management/ai-pricing/{shop_id}`

**请求体**（所有字段可选，仅更新传入的）：

```json
{
  "template_name": "aggressive",
  "auto_execute": true,
  "conservative_config": { "target_roas": 2.0, "...": "..." },
  "default_config":      { "target_roas": 3.0, "...": "..." },
  "aggressive_config":   { "target_roas": 4.0, "...": "..." }
}
```

**模板JSON字段校验**：

| 字段 | 类型 | 范围 | 说明 |
|------|------|------|------|
| target_roas | number | (0, 100] | 目标ROAS |
| min_roas | number | (0, 100] | 最低ROAS，必须 < target_roas |
| max_bid | number | [3, 10000] | 单次出价上限（卢布） |
| daily_budget | number | [0, 1000000] | 日预算（0=不限） |
| max_adjust_pct | number | (0, 100] | 单次最大调幅% |
| gross_margin | number | (0, 1) | 毛利率 |

**响应 data**：返回更新后的完整对象

**错误码**：`92002`、`10002`

### 3.3 启用AI调价

**POST** `/api/v1/bid-management/ai-pricing/{shop_id}/enable`

**业务规则**：
- 若分时调价已启用则返回 `92003`
- 首次启用前，必须满足 `shop_data_init_status.is_initialized = true`，否则返回 `92009`

**响应 data**：

```json
{ "shop_id": 1, "is_active": true, "auto_execute": false }
```

### 3.4 停用AI调价

**POST** `/api/v1/bid-management/ai-pricing/{shop_id}/disable`

停用后：
- 已生成的 `pending` 建议保留（用户可继续处理或放任次日过期）
- 不影响已执行的调价

### 3.5 手动触发AI分析

**POST** `/api/v1/bid-management/ai-pricing/{shop_id}/analyze`

立即对指定店铺执行一次AI分析，生成建议。

**请求体**（可选）：

```json
{ "campaign_ids": [101, 102] }
```

- `campaign_ids`：不传则分析店铺下全部活跃活动

**响应 data**：

```json
{
  "shop_id": 1,
  "analyzed_count": 20,
  "suggestion_count": 5,
  "auto_executed_count": 0,
  "time_cost_ms": 3421,
  "suggestions": [ /* 见 §4.1 items */ ]
}
```

**错误码**：`92002`、`92009`、`92010`、`92011`、`90001`（AI模型错误）

---

## 4. 建议列表（Suggestions）

### 4.1 获取待处理建议

**GET** `/api/v1/bid-management/suggestions/{shop_id}`

> 返回**按活动分组**的待处理建议列表。**自动过滤**昨天及以前的建议（按莫斯科日期切换）。

**查询参数**：

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| status | string | pending | pending / approved / rejected |
| campaign_id | int | - | 仅返回指定活动 |

**响应 data**：

```json
{
  "date_moscow": "2026-04-11",
  "campaigns": [
    {
      "campaign_id": 101,
      "campaign_name": "2026春季饰品推广",
      "suggestions": [
        {
          "id": 1,
          "platform_sku_id": "123456789",
          "sku_name": "银色项链套装",
          "current_bid": 50.00,
          "suggested_bid": 65.00,
          "adjust_pct": 30.00,
          "product_stage": "growing",
          "decision_basis": "history_data",
          "current_roas": 3.2,
          "expected_roas": 2.8,
          "data_days": 14,
          "reason": "当前ROAS 3.2高于目标2.5，且日预算使用率仅40%，建议加价抢量",
          "status": "pending",
          "generated_at": "2026-04-11T10:05:00Z"
        }
      ]
    }
  ]
}
```

### 4.2 确认单条建议

**POST** `/api/v1/bid-management/suggestions/{suggestion_id}/approve`

**业务规则**：
- 仅 `pending` 状态可 approve；已过期（次日）返回 `92005`
- 执行：调 Ozon API 改价 → 写 `bid_adjustment_logs` (`execute_type='ai_manual'`) → 更新 suggestion `status='approved'`, `executed_at=now()`

**响应 data**：

```json
{
  "id": 1,
  "status": "approved",
  "executed_at": "2026-04-11T15:10:00Z",
  "old_bid": 50.00,
  "new_bid": 65.00
}
```

**错误码**：`92004`、`92005`、`92006`、`92011`

### 4.3 拒绝单条建议

**POST** `/api/v1/bid-management/suggestions/{suggestion_id}/reject`

**响应 data**：

```json
{ "id": 1, "status": "rejected" }
```

### 4.4 批量确认

**POST** `/api/v1/bid-management/suggestions/approve-batch`

**请求体**：

```json
{ "ids": [1, 2, 3] }
```

**响应 data**：

```json
{
  "total": 3,
  "success": 2,
  "failed": 1,
  "results": [
    { "id": 1, "status": "approved" },
    { "id": 2, "status": "approved" },
    { "id": 3, "status": "failed", "error_code": 92011, "error_msg": "Ozon API调用失败" }
  ]
}
```

**说明**：批量操作采用"部分成功"语义，HTTP 始终返回 200，由 `results[].status` 表达每条结果。

### 4.5 批量拒绝

**POST** `/api/v1/bid-management/suggestions/reject-batch`

请求体与 §4.4 相同，返回结构一致但 status 为 `rejected`。

---

## 5. 冲突检测

### 5.1 启用前冲突检测

**GET** `/api/v1/bid-management/conflict-check/{shop_id}`

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| enabling | string | 是 | `time_pricing` / `ai_auto` |

**响应 data**：

```json
{
  "conflict": true,
  "current_active": "ai_auto",
  "message": "AI调价已启用，启用分时调价前请先停用AI调价",
  "action": "disable_ai_first"
}
```

```json
{ "conflict": false, "message": "可以启用" }
```

**业务规则**：
- 互斥策略：同一店铺的 `time_pricing_rules.is_active` 和 `ai_pricing_configs.is_active` **只能有一个为 true**
- `action` 取值：`disable_ai_first` / `disable_time_first` / `none`

---

## 6. 调价历史

### 6.1 调价日志列表

**GET** `/api/v1/bid-management/bid-logs/{shop_id}`

**查询参数**：

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| page | int | 1 | 页码 |
| size | int | 20 | 每页条数，最大100 |
| execute_type | string | all | all / time_pricing / ai_auto / ai_manual / user_manual |
| campaign_id | int | - | 活动ID筛选 |
| start_date | string | - | YYYY-MM-DD |
| end_date | string | - | YYYY-MM-DD |
| success | bool | - | true/false，不传为全部 |

**响应 data**：

```json
{
  "total": 128,
  "page": 1,
  "size": 20,
  "items": [
    {
      "id": 1001,
      "campaign_id": 101,
      "campaign_name": "2026春季饰品推广",
      "platform_sku_id": "123456789",
      "sku_name": "银色项链套装",
      "old_bid": 50.00,
      "new_bid": 60.00,
      "adjust_pct": 20.00,
      "execute_type": "time_pricing",
      "time_period": "peak",
      "period_ratio": 120,
      "product_stage": null,
      "moscow_hour": 10,
      "success": true,
      "error_msg": null,
      "created_at": "2026-04-11T10:05:00Z"
    }
  ]
}
```

---

## 7. 数据源

### 7.1 数据初始化状态

**GET** `/api/v1/bid-management/data-status/{shop_id}`

**响应 data**：

```json
{
  "shop_id": 1,
  "is_initialized": true,
  "initialized_at": "2026-04-10T02:30:00Z",
  "last_sync_at": "2026-04-11T02:05:00Z",
  "last_sync_date": "2026-04-10",
  "data_days": 92
}
```

### 7.2 手动触发数据同步

**POST** `/api/v1/bid-management/data-sync/{shop_id}`

**业务逻辑**：
- 先删除 90 天前的旧 `ad_stats` 数据
- 再调 Celery 任务 `daily_sync_task.daily_sync_shop(shop_id)`（异步）
- **必须按 shop_id 单店铺触发**，禁止全租户批量

**响应 data**：

```json
{
  "shop_id": 1,
  "task_id": "celery-uuid-xxx",
  "msg": "数据同步任务已提交，预计30秒内完成"
}
```

**错误码**：`30001`、`92010`（已在同步中）

### 7.3 数据下载（Excel）

**GET** `/api/v1/bid-management/data-download/{shop_id}`

**查询参数**：

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| days | int | 30 | 7 / 30 / 60 / 90 |

**响应**：
- Content-Type: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- Content-Disposition: `attachment; filename="shop_{id}_bid_data_{YYYYMMDD}.xlsx"`
- 注意：本接口**不走**统一响应格式，直接返回文件流

---

## 8. 错误码（92xxx 段）

| code | 常量 | 说明 |
|------|------|------|
| 0 | SUCCESS | 成功 |
| 10002 | PARAM_ERROR | 参数错误 |
| 30001 | SHOP_NOT_FOUND | 店铺不存在 |
| 40003 | LISTING_NOT_FOUND | 商品/ad_group 不存在 |
| 90001 | AI_MODEL_ERROR | AI模型调用失败 |
| 92001 | BID_TIME_RULE_NOT_FOUND | 分时调价规则不存在 |
| 92002 | BID_AI_CONFIG_NOT_FOUND | AI调价配置不存在 |
| 92003 | BID_CONFLICT_TIME_AI | 分时/AI 互斥 |
| 92004 | BID_SUGGESTION_NOT_FOUND | 调价建议不存在 |
| 92005 | BID_SUGGESTION_EXPIRED | 建议已过期（次日） |
| 92006 | BID_INVALID_STATUS | 状态不允许该操作 |
| 92007 | BID_INVALID_HOURS_CONFIG | 时段非法：24小时未覆盖/重复 |
| 92008 | BID_INVALID_RATIO | 系数越界 |
| 92009 | BID_DATA_NOT_READY | 数据未初始化 |
| 92010 | BID_DATA_SYNC_RUNNING | 数据同步中 |
| 92011 | BID_EXECUTION_FAILED | 出价执行失败（Ozon API） |
| 92012 | BID_SKU_LOCKED | SKU 已被用户手动管理 |

常量定义位置：`app/utils/errors.py`

---

## 9. Celery 调度规范

### 9.1 统一入口任务

```python
# app/tasks/celery_app.py  beat_schedule 规范
from celery.schedules import crontab

celery_app.conf.beat_schedule = {
    # 出价管理统一入口：每小时 05 分（莫斯科时间）触发
    "bid-management-hourly": {
        "task": "app.tasks.bid_management.run_bid_management",
        "schedule": crontab(minute=5),
    },
    # 每日数据同步：莫斯科凌晨 2:00
    "daily-data-sync": {
        "task": "app.tasks.data_sync.daily_sync_all_shops",
        "schedule": crontab(hour=2, minute=0),
    },

    # —— 以下保留（与出价管理无关） ——
    "daily-report":       {"task": "app.tasks.report_tasks.generate_daily_report",
                           "schedule": crontab(hour=8, minute=0)},
    "roi-alert-check":    {"task": "app.tasks.roi_alert.check_roi_anomaly",
                           "schedule": crontab(minute="*/30")},
    "ad-automation-rules":{"task": "app.tasks.ad_tasks.run_automation_rules",
                           "schedule": crontab(minute=25)},
}
```

### 9.2 删除的旧任务

以下任务由 `bid-management-hourly` 统一替代，**必须删除**：

- `ai-pricing-smart-check`（原 `ai_pricing_task.check_and_run_ai_pricing`）
- 对应地，`celery_app.conf.include` 中的 `"app.tasks.ai_pricing_task"` 也要移除

### 9.3 `run_bid_management` 执行流程规范

```
每小时05分触发
├─ 遍历所有 active Ozon 店铺
├─ 对每个店铺：
│   ├─ 查 time_pricing_rules & ai_pricing_configs
│   ├─ 两者最多一个 is_active=true（互斥由 API 层保证）
│   ├─ is_active=true → 分派给对应 executor
│   │   ├─ TimePricingExecutor.execute(shop, moscow_hour)
│   │   └─ AIPricingExecutor.execute(shop)
│   ├─ executor 内：
│   │   ├─ 跳过 ad_groups.user_managed=true 的组
│   │   ├─ 计算新出价 → 调 Ozon API → 写 bid_adjustment_logs
│   │   └─ 失败时写 last_error_msg, 设置 retry_at = now+30min
│   └─ 更新对应表 last_executed_at / last_execute_status / last_execute_result
└─ 写 TaskLog 汇总
```

### 9.4 冲突原子性保证

启用接口（§2.3 / §3.3）必须使用数据库事务 + `SELECT ... FOR UPDATE`，防止并发启用两个模式：

```python
with db.begin():
    time_rule = db.query(TimePricingRule).filter_by(shop_id=shop_id).with_for_update().first()
    ai_cfg    = db.query(AIPricingConfig).filter_by(shop_id=shop_id).with_for_update().first()
    if time_rule.is_active and enabling == "ai":
        return error(BID_CONFLICT_TIME_AI)
    if ai_cfg.is_active and enabling == "time":
        return error(BID_CONFLICT_TIME_AI)
    # ... 置 is_active=true
```

---

## 10. 数据库表对照

| 表 | 用途 | 迁移 |
|----|------|------|
| `time_pricing_rules` | 店铺级分时调价规则（单行） | 023 |
| `ai_pricing_configs` | 店铺级AI调价配置（单行，3模板JSON） | 023（DROP重建） |
| `ai_pricing_suggestions` | AI调价建议（次日过期） | 023（DROP重建） |
| `bid_adjustment_logs` | 出价调整日志（分时+AI合并） | 023 |
| `ad_groups` | 加 `user_managed/original_bid/last_auto_bid/user_managed_at` | 023 |
| `shop_data_init_status` | 加 `data_days` 字段 | 023（021创建的表） |

---

## 11. 后端文件分工（老张）

| 文件 | 职责 |
|------|------|
| `app/utils/moscow_time.py` | 莫斯科时间工具：当前时间/小时/判断时段 |
| `app/services/bid/time_pricing_executor.py` | 分时调价执行器 |
| `app/services/bid/ai_pricing_executor.py` | AI调价执行器 |
| `app/tasks/bid_management.py` | Celery 任务入口 `run_bid_management` |
| `app/api/v1/bid_management.py` | API 路由（本文档所有接口） |

### 接口与函数映射

| 接口 | service/task 函数 |
|------|------------------|
| GET /dashboard/{shop_id} | `moscow_time.get_dashboard_info(db, shop_id)` |
| PUT /time-pricing/{shop_id} | `time_pricing_executor.update_rule` |
| POST /time-pricing/{shop_id}/enable | `time_pricing_executor.enable` |
| POST /time-pricing/{shop_id}/restore-sku | `time_pricing_executor.restore_sku` |
| GET /time-pricing/{shop_id}/status | `time_pricing_executor.get_sku_status` |
| PUT /ai-pricing/{shop_id} | `ai_pricing_executor.update_config` |
| POST /ai-pricing/{shop_id}/enable | `ai_pricing_executor.enable` |
| POST /ai-pricing/{shop_id}/analyze | `ai_pricing_executor.analyze_now` |
| POST /suggestions/{id}/approve | `ai_pricing_executor.approve_suggestion` |
| GET /conflict-check/{shop_id} | `bid_management.check_conflict` |

---

## 12. 前端 Mock 契约（小明）

在后端未就绪期间，小明可基于下述响应样例用 Mock 数据开发页面：

1. **状态栏轮询**：每 30s 调一次 §1.1，前端根据 `active_mode` 切换Tab默认选中
2. **分时调价 Tab**：GET §2.1 展示配置 → PUT §2.2 保存 → POST §2.3/2.4 开关
3. **AI调价 Tab**：GET §3.1 → PUT §3.2 → POST §3.3/3.4 → 点"立即分析" §3.5
4. **建议列表**：GET §4.1 按活动分组渲染 → 批量勾选 → POST §4.4/4.5
5. **调价历史**：GET §6.1 分页表格，按 `execute_type` 过滤加 Tab
6. **数据源**：GET §7.1 + POST §7.2 刷新 + GET §7.3 下载

Mock 数据可直接复用本文档的所有 JSON 样例。

---

## 13. 版本历史

| 日期 | 版本 | 作者 | 变更 |
|------|------|------|------|
| 2026-04-11 | v1 | 老林 | 初稿：合并分时调价 + AI调价，DROP旧 ai_pricing_* 重建 |
