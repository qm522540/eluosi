# AI智能调价 API 接口文档

> 模块：AI Smart Pricing  
> 前缀：`/api/ai-pricing`  
> 认证：所有接口需携带 `Authorization: Bearer <token>`  
> 多租户隔离：基于JWT中的tenant_id自动过滤

## 统一响应格式

```json
{
  "code": 0,
  "msg": "success",
  "data": {},
  "timestamp": 1712764800
}
```

错误时 `code` 非0，`msg` 返回错误描述，`data` 为 `null`。

---

## 1. 获取店铺调价配置

**GET** `/api/ai-pricing/configs/{shop_id}`

获取指定店铺下所有品类的调价配置列表。

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| shop_id | int | 店铺ID |

**响应 data：**

```json
[
  {
    "id": 1,
    "shop_id": 1,
    "category_name": "饰品",
    "target_roas": 2.50,
    "min_roas": 1.50,
    "gross_margin": 0.60,
    "daily_budget_limit": 2000.00,
    "max_bid": 150.00,
    "min_bid": 3.00,
    "max_adjust_pct": 30.00,
    "auto_execute": false,
    "is_active": true,
    "created_at": "2026-04-10T10:00:00",
    "updated_at": "2026-04-10T10:00:00"
  }
]
```

---

## 2. 更新调价配置

**PUT** `/api/ai-pricing/configs/{config_id}`

更新指定品类的调价参数。

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| config_id | int | 配置记录ID |

**请求体：**

```json
{
  "target_roas": 2.80,
  "min_roas": 1.60,
  "gross_margin": 0.55,
  "daily_budget_limit": 2500.00,
  "max_bid": 180.00,
  "min_bid": 5.00,
  "max_adjust_pct": 25.00,
  "auto_execute": false,
  "is_active": true
}
```

所有字段均为可选，仅更新传入的字段。

**响应 data：**

```json
{
  "id": 1,
  "category_name": "饰品",
  "target_roas": 2.80,
  "min_roas": 1.60,
  "gross_margin": 0.55,
  "daily_budget_limit": 2500.00,
  "max_bid": 180.00,
  "min_bid": 5.00,
  "max_adjust_pct": 25.00,
  "auto_execute": false,
  "is_active": true,
  "updated_at": "2026-04-10T12:00:00"
}
```

**校验规则：**
- `min_roas` < `target_roas`
- `min_bid` < `max_bid`
- `gross_margin` 范围 0.01 ~ 0.99
- `max_adjust_pct` 范围 1 ~ 100
- `daily_budget_limit` > 0

---

## 3. 手动触发AI分析

**POST** `/api/ai-pricing/analyze/{shop_id}`

立即对指定店铺执行AI调价分析，返回生成的建议列表。

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| shop_id | int | 店铺ID |

**请求体（可选）：**

```json
{
  "category_name": "饰品",
  "campaign_ids": [101, 102]
}
```

- `category_name`：仅分析指定品类，不传则分析所有品类
- `campaign_ids`：仅分析指定活动，不传则分析店铺下所有活跃活动

**响应 data：**

```json
{
  "analyzed_count": 5,
  "suggestion_count": 3,
  "suggestions": [
    {
      "id": 1,
      "campaign_id": 101,
      "product_id": "SKU12345",
      "product_name": "银色项链套装",
      "current_bid": 50.00,
      "suggested_bid": 65.00,
      "adjust_pct": 30.00,
      "reason": "当前ROAS 3.2高于目标2.5，且日预算使用率仅40%，建议加价抢量",
      "current_roas": 3.20,
      "expected_roas": 2.80,
      "current_spend": 800.00,
      "daily_budget": 2000.00,
      "status": "pending",
      "expires_at": "2026-04-10T14:00:00"
    }
  ]
}
```

---

## 4. 获取待确认建议列表

**GET** `/api/ai-pricing/suggestions/{shop_id}`

获取指定店铺的调价建议列表，支持分页和状态筛选。

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| shop_id | int | 店铺ID |

**查询参数：**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| status | string | pending | 筛选状态：pending/approved/rejected/executed/expired |
| page | int | 1 | 页码 |
| page_size | int | 20 | 每页条数，最大100 |

**响应 data：**

```json
{
  "total": 15,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "id": 1,
      "campaign_id": 101,
      "product_id": "SKU12345",
      "product_name": "银色项链套装",
      "current_bid": 50.00,
      "suggested_bid": 65.00,
      "adjust_pct": 30.00,
      "reason": "当前ROAS 3.2高于目标2.5，建议加价抢量",
      "current_roas": 3.20,
      "expected_roas": 2.80,
      "current_spend": 800.00,
      "daily_budget": 2000.00,
      "ai_model": "deepseek",
      "status": "pending",
      "auto_executed": false,
      "created_at": "2026-04-10T12:00:00",
      "expires_at": "2026-04-10T14:00:00"
    }
  ]
}
```

---

## 5. 确认执行建议

**POST** `/api/ai-pricing/suggestions/{suggestion_id}/approve`

人工确认并执行一条AI调价建议，调用平台API修改出价。

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| suggestion_id | int | 建议记录ID |

**响应 data：**

```json
{
  "id": 1,
  "status": "executed",
  "executed_at": "2026-04-10T12:30:00",
  "product_id": "SKU12345",
  "old_bid": 50.00,
  "new_bid": 65.00,
  "api_response": "ok"
}
```

**业务规则：**
- 仅 `pending` 状态可approve
- 已过期（`expires_at` < now）的建议自动标记为 `expired`，不可执行
- 执行成功后 `status` 改为 `executed`，记录 `executed_at`

---

## 6. 拒绝建议

**POST** `/api/ai-pricing/suggestions/{suggestion_id}/reject`

拒绝一条AI调价建议，不做出价变更。

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| suggestion_id | int | 建议记录ID |

**响应 data：**

```json
{
  "id": 1,
  "status": "rejected"
}
```

**业务规则：**
- 仅 `pending` 状态可reject

---

## 7. 切换自动/建议模式

**POST** `/api/ai-pricing/toggle-auto/{shop_id}`

切换指定店铺所有品类配置的执行模式。

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| shop_id | int | 店铺ID |

**请求体：**

```json
{
  "auto_execute": true,
  "category_name": "饰品"
}
```

- `auto_execute`：true=自动模式（AI分析后直接执行）, false=建议模式（需人工确认）
- `category_name`：可选，指定品类切换；不传则切换该店铺所有品类

**响应 data：**

```json
{
  "shop_id": 1,
  "updated_count": 3,
  "auto_execute": true
}
```

---

## 8. 获取调价历史记录

**GET** `/api/ai-pricing/history/{shop_id}`

获取指定店铺的调价执行历史（已执行+已拒绝+已过期），按时间倒序。

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| shop_id | int | 店铺ID |

**查询参数：**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| status | string | - | 筛选状态：executed/rejected/expired，不传返回全部非pending |
| start_date | string | - | 起始日期，格式 YYYY-MM-DD |
| end_date | string | - | 结束日期，格式 YYYY-MM-DD |
| page | int | 1 | 页码 |
| page_size | int | 20 | 每页条数，最大100 |

**响应 data：**

```json
{
  "total": 42,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "id": 10,
      "campaign_id": 101,
      "product_id": "SKU12345",
      "product_name": "银色项链套装",
      "current_bid": 50.00,
      "suggested_bid": 65.00,
      "adjust_pct": 30.00,
      "reason": "ROAS优秀，加价抢量",
      "current_roas": 3.20,
      "expected_roas": 2.80,
      "ai_model": "deepseek",
      "status": "executed",
      "auto_executed": false,
      "executed_at": "2026-04-10T12:30:00",
      "created_at": "2026-04-10T12:00:00"
    }
  ]
}
```

---

## 错误码

| code | msg | 说明 |
|------|-----|------|
| 0 | success | 成功 |
| 1001 | config not found | 配置不存在 |
| 1002 | suggestion not found | 建议记录不存在 |
| 1003 | suggestion expired | 建议已过期 |
| 1004 | invalid status | 状态不允许该操作 |
| 1005 | validation error | 参数校验失败 |
| 1006 | api call failed | 调用平台API失败 |
| 1007 | shop not found | 店铺不存在 |
