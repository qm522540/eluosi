# 店铺克隆（Store Clone）模块 API 接口规范

> 模块：店铺克隆（Store Clone）
> 前缀：`/api/v1/clone`
> 平台范围：**Phase 1 仅 Ozon**；WB / Yandex Phase 1.5 后续
> 业务模型：A 店自动跟踪 B 店上新 → 抓取改写 → 入待审核 → 用户批准 → 推 A 上架
> 认证：所有接口需携带 `Authorization: Bearer <token>`
> 多租户隔离：所有查询/写入必须带 `tenant_id` 过滤（CLAUDE.md 规则 1）
> 手动触发接口必须按 `shop_id` 过滤（CLAUDE.md 规则 4）
> 时间字段：DB 存真 UTC naive，唯一入口 `utc_now_naive()`（CLAUDE.md 规则 6）
> 架构师：老林
> 版本：v1（2026-05-02）

---

## 0. 通用约定

### 0.1 统一响应格式

```json
{
  "code": 0,
  "msg": "success",
  "data": {},
  "timestamp": 1746124800
}
```

成功 `code=0`，其余为错误码（见 §7）。失败时 `data=null`。

### 0.2 时间字段统一规范

- 存储：MySQL `DATETIME` 存真 UTC naive
- 返回：ISO 8601 UTC 字符串，如 `2026-05-02T08:30:00Z`
- 莫斯科展示字段（如 `moscow_time`）通过 `app.utils.moscow_time._iso()` 渲染

### 0.3 金额字段规范

- 单位：**卢布（RUB）**，`DECIMAL(10,2)`
- Ozon API 调用时再做纳卢布换算（×1000000）

### 0.4 店铺作用域强制规则

> 所有手动触发类接口（scan-now / approve / reject 等）**必须**按 `shop_id` 或 `task_id` 过滤，禁止全租户批处理。
> Celery Beat（`clone-daily-scan` / `clone-publish-pending`）走全租户扫描，按 `is_active=1` 过滤，是定时任务的合理行为（CLAUDE.md 规则 4 例外）。

### 0.5 分页参数约定

- `page`：默认 1，最小 1
- `size`：默认 20，最大 100
- 返回字段：`total` / `page` / `size` / `items`

---

## 1. 路线图

### Phase 1（本期，1-2 周）：自营双店克隆

- B 店是用户自己另一个店（`shops` 表里有 seller token 的店）
- 数据来源：seller API（平台官方"商品列表"接口）
- 优先 **Ozon**（API 最完整）→ WB → Yandex 顺序逐平台开

### Phase 2（架构留口，后期）：竞品公开 API 跟卖

- B 店是别人的店
- 数据来源：平台公开 API
- **平台能力差异（Phase 2 规划必须知道）**：

| 平台 | 公开 API 能否"列出某店全部商品" | 能否"自动检测上新" |
|---|---|---|
| WB | ✅ 能（按 supplier_id） | ✅ 增量比对可行 |
| **Ozon** | ❌ 无稳定接口 | ❌ Phase 2 在 Ozon 只能"用户粘 SKU 列表→批量克隆"，**无法自动检测上新** |
| Yandex | 部分能 | 弱 |

- 实现策略：Provider 抽象层隔离（§2），Phase 2 加 `PublicApiProvider`，业务层零改造

### Phase 3（独立需求，后期）：高级配置

- 跟价（`follow_price_change=1` 后续扩展为档位策略）
- 跟图、跟描述（B 改了 A 触发待审）
- 多 B 店合并到同一 A 店（多对一）

---

## 2. Provider 抽象（架构核心）

为 Phase 2 不返工，数据来源层从 Phase 1 起就抽象。

```python
# app/services/clone/providers/base.py

@dataclass
class ProductSnapshot:
    """B 店商品的完整业务快照（provider-agnostic）"""
    source_platform: str             # wb / ozon / yandex
    source_sku_id: str               # B 平台 SKU
    title_ru: str
    description_ru: str
    price_rub: Decimal
    stock: int
    images: list[str]                # 图片 URL 列表
    platform_category_id: str        # B 平台分类 ID
    platform_category_name: str
    attributes: list[dict]           # [{key, value, ...}]
    raw: dict                        # 原始 API 响应（debug 用）
    detected_at: datetime            # 抓取时间（utc_now_naive）

class BaseShopProvider(ABC):
    @abstractmethod
    async def list_new_products(
        self, since: datetime, limit: int = 100,
    ) -> list[ProductSnapshot]:
        """列 B 店在 since 之后上新的商品"""

    @abstractmethod
    async def get_product_detail(self, source_sku_id: str) -> ProductSnapshot:
        """按 SKU 拉单条详情"""
```

### Phase 1 实现

```python
# app/services/clone/providers/seller_api.py
class SellerApiProvider(BaseShopProvider):
    """走 seller API token，B 店必须是 shops 表里的店"""
    def __init__(self, db: Session, source_shop: Shop): ...
```

### Phase 2 占位

```python
# app/services/clone/providers/public_api.py（Phase 2 实现）
class PublicApiProvider(BaseShopProvider):
    """走平台公开商品 API；Ozon 平台只支持 SKU 列表批量"""
```

---

## 3. 数据库表

### 3.1 ALTER 现有表 — `platform_listings` 加追溯字段（migration 061）

**关键设计**：克隆抓取的商品**入库到 `platform_listings`**（用 `status='inactive'`），这样能直接复用现有 SEO AI 改写接口（`optimize_title` / `generate_description`），SEO 模块未来改进规则克隆自动跟着受益。

```sql
-- migration 061_platform_listings_clone_task_id.sql
ALTER TABLE `platform_listings`
    ADD COLUMN `clone_task_id` INT DEFAULT NULL
        COMMENT '克隆任务 ID；非 NULL = 克隆草稿；NULL = 普通 listing',
    ADD INDEX `idx_clone_task` (`clone_task_id`);
```

**status 字段处理约定**（不动 status ENUM，避免污染现有 8 个文件的 `WHERE status='active'` 查询）：

| 阶段 | `status` | `clone_task_id` |
|---|---|---|
| 克隆抓取入库 | `inactive` | 任务 ID（非 NULL） |
| 用户审核通过 + 推 A 上架成功 | `active` | 保留 ID 做追溯 |
| 用户拒绝 | `deleted` | 保留 |

`status='inactive'` 自动让现有 `WHERE status='active'` 查询忽略克隆草稿；`clone_task_id IS NOT NULL` 用于区分"用户主动停售"和"克隆草稿"。

### 3.2 `clone_tasks` — 克隆任务（A ← B 关系 + 配置）

```sql
CREATE TABLE `clone_tasks` (
    `id`                INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`         INT UNSIGNED NOT NULL,
    `target_shop_id`    INT UNSIGNED NOT NULL  COMMENT 'A 店（落地店）',
    `source_shop_id`    INT UNSIGNED DEFAULT NULL  COMMENT 'B 店；Phase 1 必填，Phase 2 公开 API 模式可空',
    `source_type`       ENUM('seller_api','public_api') NOT NULL DEFAULT 'seller_api',

    -- Phase 2 留口（Phase 1 全空）
    `source_platform`       VARCHAR(20) DEFAULT NULL  COMMENT 'Phase 2: 公开 API 时记录 B 平台',
    `source_external_id`    VARCHAR(200) DEFAULT NULL COMMENT 'Phase 2: 竞品 supplier_id / shop_url',
    `source_sku_whitelist`  JSON DEFAULT NULL         COMMENT 'Phase 2: Ozon 公开 API 的手动 SKU 列表',

    `is_active`         TINYINT NOT NULL DEFAULT 0,

    -- 配置
    `title_mode`        ENUM('original','ai_rewrite') NOT NULL DEFAULT 'original',
    `desc_mode`         ENUM('original','ai_rewrite') NOT NULL DEFAULT 'original',
    `price_mode`        ENUM('same','adjust_pct') NOT NULL DEFAULT 'same',
    `price_adjust_pct`  DECIMAL(5,2) DEFAULT NULL COMMENT '正数=涨，负数=跌；price_mode=adjust_pct 时必填',
    `default_stock`     INT NOT NULL DEFAULT 999,
    `follow_price_change` TINYINT NOT NULL DEFAULT 0 COMMENT '1=B 改价 A 自动跟（不走审核）',

    -- 类目映射策略
    `category_strategy` ENUM('same_platform','use_local_map','reject_if_missing')
                        NOT NULL DEFAULT 'use_local_map'
                        COMMENT '同平台直接复用 / 跨平台走 028 映射 / 缺失即拒',

    -- 运行状态
    `last_check_at`     DATETIME DEFAULT NULL,
    `last_found_count`  INT NOT NULL DEFAULT 0,
    `last_publish_count` INT NOT NULL DEFAULT 0 COMMENT '上次扫描入待审数',
    `last_skip_count`   INT NOT NULL DEFAULT 0 COMMENT '上次扫描跳过数（已发布/已拒绝）',
    `last_error_msg`    VARCHAR(500) DEFAULT NULL,

    `created_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_target_source` (`tenant_id`, `target_shop_id`, `source_shop_id`),
    INDEX `idx_active`  (`tenant_id`, `is_active`),
    INDEX `idx_target`  (`target_shop_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='店铺克隆任务（A 店 ← B 店关系 + 配置）';
```

**业务规则**：
- `(target_shop_id, source_shop_id)` 唯一：同一对 A/B 店只能有一条任务（一个方向）
- 反向（B → A）允许：是另一条记录
- `target_shop_id` 必须属于 `tenant_id`（路由层 `get_owned_shop` 守卫）
- `source_shop_id` 必须属于同一 `tenant_id`（service 层校验，不允许跨租户跟踪）

### 3.3 `clone_pending_products` — 待审核商品（核心交互区）

```sql
CREATE TABLE `clone_pending_products` (
    `id`                INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`         INT UNSIGNED NOT NULL,
    `task_id`           INT UNSIGNED NOT NULL,

    -- 来源
    `source_shop_id`    INT UNSIGNED DEFAULT NULL,
    `source_platform`   VARCHAR(20) NOT NULL,
    `source_sku_id`     VARCHAR(100) NOT NULL,

    -- B 商品快照（抓取瞬间）
    `source_snapshot`   JSON NOT NULL COMMENT '完整 ProductSnapshot dict',

    -- 应用规则后的 A 商品 payload（供用户审核 + 发布）
    `proposed_payload`  JSON NOT NULL COMMENT '{title_ru, description_ru, price, stock, images, platform_category_id, attributes}',

    -- 关联 platform_listings 草稿（AI 改写复用 SEO 接口的锚点）
    `draft_listing_id`  INT UNSIGNED DEFAULT NULL,

    -- 状态机
    `status`            ENUM('pending','approved','rejected','published','failed')
                        NOT NULL DEFAULT 'pending',
    `category_mapping_status` ENUM('ok','missing','ai_suggested') NOT NULL DEFAULT 'ok',
    `reject_reason`     VARCHAR(200) DEFAULT NULL,
    `publish_error_msg` VARCHAR(500) DEFAULT NULL,

    -- 审计
    `detected_at`       DATETIME NOT NULL,
    `reviewed_at`       DATETIME DEFAULT NULL,
    `reviewed_by`       INT UNSIGNED DEFAULT NULL,
    `published_at`      DATETIME DEFAULT NULL,
    `target_platform_sku_id` VARCHAR(100) DEFAULT NULL COMMENT 'A 店上架后的 SKU',

    `created_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_task_source_sku` (`task_id`, `source_sku_id`)
        COMMENT '同一任务下同一来源 SKU 只能有一条（避免重复抓取）',
    INDEX `idx_status`  (`tenant_id`, `status`),
    INDEX `idx_task_status` (`task_id`, `status`),
    INDEX `idx_draft_listing` (`draft_listing_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='店铺克隆待审核商品队列';
```

**业务规则**：
- `UNIQUE KEY (task_id, source_sku_id)` 强制：同一 B SKU 只能在某任务下出现一次（决策 5 永久跳过的物理保障）
- 用户 reject 不删除记录，扫描时如发现 `status='rejected'` 跳过并计入 `clone_logs.detail.skip_rejected`
- `published` 后该记录历史保留，`clone_published_links` 表是它的"上架后"延续

### 3.4 `clone_logs` — 克隆日志（扫描 + 审核 + 发布）

```sql
CREATE TABLE `clone_logs` (
    `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`       INT UNSIGNED NOT NULL,
    `task_id`         INT UNSIGNED DEFAULT NULL COMMENT '系统级日志可空',
    `log_type`        ENUM('scan','review','publish','price_sync') NOT NULL,
    `status`          ENUM('success','partial','failed','skipped') NOT NULL,
    `rows_affected`   INT NOT NULL DEFAULT 0,
    `duration_ms`     INT DEFAULT NULL,

    -- scan 类型 detail 结构：
    -- {
    --   "found": 120,                    -- B 店本次扫描总返回数
    --   "new": 3,                        -- 新增入待审条数
    --   "skip_published": 105,           -- 已 published 跳过
    --   "skip_rejected": 12,             -- 已 rejected 跳过
    --   "skip_category_missing": 0,     -- 类目映射缺失跳过
    --   "skipped_skus": [
    --     {"sku":"123","reason":"published"},
    --     {"sku":"456","reason":"rejected"},
    --     {"sku":"789","reason":"category_missing","detail":"B 平台类目 X 未映射"}
    --   ]
    -- }
    `detail`          JSON DEFAULT NULL,
    `error_msg`       VARCHAR(500) DEFAULT NULL,

    `created_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_task_type` (`task_id`, `log_type`, `created_at`),
    INDEX `idx_tenant_created` (`tenant_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='店铺克隆日志（扫描/审核/发布/跟价）';
```

### 3.5 `clone_published_links` — 已发布关系表（追溯 + 跟价用）

```sql
CREATE TABLE `clone_published_links` (
    `id`                       INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`                INT UNSIGNED NOT NULL,
    `task_id`                  INT UNSIGNED NOT NULL,
    `pending_id`               INT UNSIGNED NOT NULL COMMENT '原 clone_pending_products.id',
    `source_platform`          VARCHAR(20) NOT NULL,
    `source_sku_id`            VARCHAR(100) NOT NULL,
    `target_shop_id`           INT UNSIGNED NOT NULL,
    `target_platform_sku_id`   VARCHAR(100) NOT NULL,
    `target_listing_id`        INT UNSIGNED DEFAULT NULL COMMENT '关联 platform_listings.id',
    `last_synced_price`        DECIMAL(10,2) DEFAULT NULL,
    `last_synced_at`           DATETIME DEFAULT NULL,
    `published_at`             DATETIME NOT NULL,
    `created_at`               DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_pending` (`pending_id`),
    INDEX `idx_task` (`task_id`),
    INDEX `idx_source` (`source_platform`, `source_sku_id`),
    INDEX `idx_target` (`target_platform_sku_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='店铺克隆已发布关系（追溯 + follow_price_change 跟价数据源）';
```

---

## 4. 业务流程

### 4.1 扫描流程（`clone-daily-scan` 或手动 `/scan-now`）

```
对每个 is_active=1 的 task：
1. provider = SellerApiProvider(db, source_shop)
2. snapshots = provider.list_new_products(since=task.last_check_at)
3. 对每个 snapshot：
   a. 查 clone_pending_products(task_id, source_sku_id)
      - 存在且 status='published' → skip (skip_published++)
      - 存在且 status='rejected'  → skip (skip_rejected++)
      - 存在且 status='pending'   → skip 已在队列（防扫描间夹带）
   b. 类目映射判定（按 task.category_strategy）：
      - same_platform：source_platform == target_platform → 直接复用 platform_category_id
      - use_local_map：跨平台 → 查 028 表（B → 本地 → A），缺失则按 reject_if_missing 处理
      - reject_if_missing：缺失 → skip + 记 skip_category_missing
   c. 价格规则（按 task.price_mode）：
      - same: target_price = source_price
      - adjust_pct: target_price = source_price * (1 + price_adjust_pct/100)
   d. INSERT platform_listings（status='inactive', clone_task_id=task.id）→ 拿 draft_listing_id
   e. 图片处理：oss_client.download_images_batch(images, prefix="clone/{tenant}/{task}/{sku}")
   f. 标题处理：
      - title_mode=original → proposed.title_ru = source.title_ru
      - title_mode=ai_rewrite → proposed.title_ru = await optimize_title(db, draft_listing_id, tenant_id).new_title
   g. 描述处理：
      - desc_mode=original → proposed.description_ru = source.description_ru
      - desc_mode=ai_rewrite → proposed.description_ru = await generate_description(db, draft_listing_id, tenant_id, target_platform).description
   h. UPDATE platform_listings SET title_ru/description_ru = proposed
   i. INSERT clone_pending_products(status='pending', source_snapshot, proposed_payload, draft_listing_id)
   j. new++
4. 写 clone_logs(log_type='scan', detail={found, new, skip_*, skipped_skus})
5. UPDATE clone_tasks SET last_check_at, last_found_count, last_publish_count, last_skip_count
```

### 4.2 审核 + 发布流程

```
用户 POST /pending/{id}/approve
1. UPDATE clone_pending_products SET status='approved', reviewed_at, reviewed_by

clone-publish-pending Beat 每 5 分钟扫一次 status='approved'：
1. 调 A 平台 SDK 上架（使用 proposed_payload）
2. 成功：
   - UPDATE platform_listings SET status='active', platform_sku_id=<新 SKU>
   - INSERT clone_published_links
   - UPDATE clone_pending_products SET status='published', published_at, target_platform_sku_id
   - 写 clone_logs(log_type='publish', status='success')
3. 失败：
   - UPDATE clone_pending_products SET status='failed', publish_error_msg
   - 写 clone_logs(log_type='publish', status='failed')
   - 用户可在前端重新编辑 proposed_payload 后重新 approve
```

### 4.3 跟价流程（仅 `follow_price_change=1` 的任务）

```
clone-daily-scan 中，对每个 task：
- 若 follow_price_change=1：
  - 查 clone_published_links（task_id 下所有已发布商品）
  - provider.get_product_detail(source_sku_id) → 当前 B 价
  - 应用 price_mode + price_adjust_pct → A 目标价
  - 与 last_synced_price 比较，差异 > 0.5% 才调
  - 调 A 平台改价 API（**不走审核**，直接生效）
  - UPDATE clone_published_links SET last_synced_price, last_synced_at
  - 写 clone_logs(log_type='price_sync')
```

---

## 5. 接口规范

### 5.1 任务管理

#### 5.1.1 创建任务

**POST** `/api/v1/clone/tasks`

请求体：

```json
{
  "target_shop_id": 1,
  "source_shop_id": 7,
  "title_mode": "ai_rewrite",
  "desc_mode": "original",
  "price_mode": "adjust_pct",
  "price_adjust_pct": 10.00,
  "default_stock": 999,
  "follow_price_change": false,
  "category_strategy": "use_local_map",
  "is_active": true
}
```

**校验**：
- `target_shop_id` 必须属于当前 `tenant_id`（service 层 `get_owned_shop` 思路）
- `source_shop_id` 必须属于同一 `tenant_id`
- `target_shop_id != source_shop_id`
- `price_mode='adjust_pct'` 时 `price_adjust_pct` 必填，范围 `[-50, 200]`
- `default_stock` 范围 `[0, 999999]`
- 唯一约束：同一 `(target_shop_id, source_shop_id)` 只能一条任务

响应 data：返回完整 task 对象

错误码：`30001`、`95001`、`95002`、`95003`、`10002`

#### 5.1.2 获取任务列表

**GET** `/api/v1/clone/tasks`

查询参数：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| target_shop_id | int | - | 按 A 店过滤 |
| is_active | bool | - | 按启用状态过滤 |
| page / size | - | 1/20 | 分页 |

响应 data：

```json
{
  "total": 5,
  "page": 1, "size": 20,
  "items": [
    {
      "id": 1,
      "target_shop": {"id": 1, "name": "Shario", "platform": "wb"},
      "source_shop": {"id": 7, "name": "PT.Gril", "platform": "wb"},
      "is_active": true,
      "title_mode": "ai_rewrite",
      "desc_mode": "original",
      "price_mode": "adjust_pct",
      "price_adjust_pct": 10.00,
      "follow_price_change": false,
      "category_strategy": "use_local_map",
      "last_check_at": "2026-05-02T03:30:12Z",
      "last_publish_count": 3,
      "last_skip_count": 117,
      "pending_count": 8,
      "published_count": 42
    }
  ]
}
```

#### 5.1.3 获取任务详情

**GET** `/api/v1/clone/tasks/{task_id}`

响应 data：完整 task 对象 + `recent_logs`（近 10 条）

错误码：`95001`

#### 5.1.4 更新任务配置

**PUT** `/api/v1/clone/tasks/{task_id}`

请求体：所有字段可选，仅更新传入的（除 `target_shop_id` / `source_shop_id` 不可改）

错误码：`95001`、`95002`、`10002`

#### 5.1.5 启用 / 停用

**POST** `/api/v1/clone/tasks/{task_id}/enable`
**POST** `/api/v1/clone/tasks/{task_id}/disable`

启用前校验：
- `target_shop` 平台已配置且 active
- `source_shop` 平台凭证有效（一次性 `ping` 检查）
- 跨平台情形下 `category_strategy != 'reject_if_missing'` 时给个 warning（不强阻塞）

错误码：`95001`、`30002`、`95004`

#### 5.1.6 手动触发一次扫描

**POST** `/api/v1/clone/tasks/{task_id}/scan-now`

业务规则：
- 同步触发 `_run_scan(task_id)`（不走 Celery，立刻看结果）
- 加 Redis 锁 `clone:scan:lock:{task_id}` TTL 600s 防并发
- 超时 60s 后转后台异步（返回 task_run_id）

响应 data：

```json
{
  "found": 12,
  "new": 3,
  "skip_published": 7,
  "skip_rejected": 2,
  "skip_category_missing": 0,
  "duration_ms": 8420,
  "log_id": 1042
}
```

错误码：`95001`、`95005`（扫描进行中）、`95006`（B 店凭证失效）

#### 5.1.7 删除任务

**DELETE** `/api/v1/clone/tasks/{task_id}`

业务规则：
- 软删（`is_active=0`）+ 保留所有 pending / logs / published_links 历史
- 已发布的 listing 不下架（用户手动到平台后台处理）

---

### 5.2 待审核商品

#### 5.2.1 待审核列表

**GET** `/api/v1/clone/pending`

查询参数：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| task_id | int | - | 按任务过滤（不传返回当前租户全部） |
| status | string | pending | pending / approved / rejected / published / failed |
| category_mapping_status | string | - | ok / missing / ai_suggested |
| keyword | string | - | source_sku_id / title 模糊搜索 |
| page / size | - | 1/20 | 分页 |

响应 data：

```json
{
  "total": 8,
  "page": 1, "size": 20,
  "items": [
    {
      "id": 101,
      "task_id": 1,
      "source": {
        "platform": "wb",
        "sku_id": "123456789",
        "title_ru": "Серебряное кольцо с топазом",
        "description_ru": "...",
        "price_rub": 2400.00,
        "stock": 5,
        "images": ["https://wb.cdn/...", "..."],
        "platform_category_name": "Кольца"
      },
      "proposed": {
        "title_ru": "Серебряное кольцо женское топаз — премиум",
        "description_ru": "...（AI 改写后）",
        "price_rub": 2640.00,
        "stock": 999,
        "images_oss": ["https://oss.cdn/clone/4/1/123456789/00-abc.jpg"],
        "platform_category_id": "8126",
        "platform_category_name": "Украшения / Кольца",
        "attributes": [...]
      },
      "category_mapping_status": "ok",
      "status": "pending",
      "detected_at": "2026-05-02T03:30:15Z"
    }
  ]
}
```

#### 5.2.2 单条批准

**POST** `/api/v1/clone/pending/{pending_id}/approve`

业务规则：
- 仅 `status IN ('pending','failed')` 可 approve
- 状态置 `approved`，等 `clone-publish-pending` Beat 异步处理
- 同步返回不等发布结果

响应 data：

```json
{ "id": 101, "status": "approved", "queued_at": "2026-05-02T15:10:00Z" }
```

错误码：`95007`、`95008`

#### 5.2.3 单条拒绝

**POST** `/api/v1/clone/pending/{pending_id}/reject`

请求体：

```json
{ "reject_reason": "类目错误" }
```

业务规则：
- 仅 `status='pending'` 可 reject
- UPDATE platform_listings 草稿 SET status='deleted'
- 该 source_sku_id 永久跳过（决策 5）

#### 5.2.4 编辑 proposed_payload（审核前修改）

**PUT** `/api/v1/clone/pending/{pending_id}`

请求体（所有字段可选）：

```json
{
  "proposed_payload": {
    "title_ru": "用户手动改的标题",
    "price_rub": 2700.00,
    ...
  }
}
```

业务规则：
- 仅 `status='pending'` 可 edit
- 同步更新 `platform_listings` 草稿对应字段

#### 5.2.5 批量批准 / 拒绝

**POST** `/api/v1/clone/pending/approve-batch`
**POST** `/api/v1/clone/pending/reject-batch`

请求体：

```json
{ "ids": [101, 102, 103], "reject_reason": "..." }
```

响应：部分成功语义，HTTP 200 + `results[].status` 表达每条结果。

---

### 5.3 日志

#### 5.3.1 日志列表

**GET** `/api/v1/clone/logs`

查询参数：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| task_id | int | - | 按任务过滤 |
| log_type | string | all | scan / review / publish / price_sync |
| status | string | all | success / partial / failed / skipped |
| start_date / end_date | YYYY-MM-DD | - | 时间范围 |
| page / size | - | 1/20 | |

响应 data 结构同 `bid-logs`，`detail` JSON 字段前端展开渲染。

---

### 5.4 配置辅助

#### 5.4.1 列出可用作 source / target 的店铺

**GET** `/api/v1/clone/available-shops`

响应：当前 tenant 下所有 active 店铺 + 平台 + 是否有 seller token。前端用于"创建任务"向导的下拉。

#### 5.4.2 类目映射健康检查（可选）

**GET** `/api/v1/clone/category-coverage/{task_id}`

业务：扫描 source_shop 近 100 个商品，统计哪些 B 平台分类**无映射**到 A 平台。引导用户先去映射管理建好再启用任务。

响应 data：

```json
{
  "checked": 100,
  "missing_categories": [
    {"platform_category_id": "8126", "platform_category_name": "Кольца", "sku_count": 23}
  ],
  "ready_pct": 77
}
```

---

## 6. Celery 调度规范

```python
# app/tasks/celery_app.py beat_schedule

celery_app.conf.beat_schedule = {
    # ... 既有任务 ...

    # 店铺克隆每日扫描（含跟价）
    "clone-daily-scan": {
        "task": "app.tasks.clone_tasks.daily_scan_all_tasks",
        "schedule": crontab(hour=3, minute=30),  # MSK 03:30
    },
    # 已批准的待发布商品异步推上架
    "clone-publish-pending": {
        "task": "app.tasks.clone_tasks.publish_approved_pending",
        "schedule": crontab(minute="*/5"),
    },
}
```

### 6.1 `daily_scan_all_tasks`

```
遍历所有 is_active=1 的 clone_tasks（全租户）：
- 每个 task 加 Redis 锁 clone:scan:lock:{task_id} TTL=900s
- 调 _run_scan(task_id)
- 异常隔离：单 task 失败不影响其他
- 写汇总 task_log
```

### 6.2 `publish_approved_pending`

```
查 clone_pending_products WHERE status='approved' LIMIT 50
对每条：
- 加 Redis 锁 clone:publish:lock:{pending_id} TTL=300s
- 调 A 平台上架 API
- 成功 → status='published'，写 clone_published_links
- 失败 → status='failed' + publish_error_msg（不重试，等用户重新 approve）
```

---

## 7. 错误码（95xxx 段）

| code | 常量 | 说明 |
|---|---|---|
| 0 | SUCCESS | 成功 |
| 10002 | PARAM_ERROR | 参数错误 |
| 30001 | SHOP_NOT_FOUND | 店铺不存在 |
| 30002 | SHOP_CREDENTIAL_INVALID | 店铺凭证无效 |
| 95001 | CLONE_TASK_NOT_FOUND | 克隆任务不存在 |
| 95002 | CLONE_TASK_DUPLICATE | 任务已存在（同一对 A/B） |
| 95003 | CLONE_TASK_INVALID_CONFIG | 配置非法（adjust_pct 缺失/超界等） |
| 95004 | CLONE_TASK_SOURCE_INVALID | 源店铺不可用（不属于本租户/已 inactive） |
| 95005 | CLONE_SCAN_RUNNING | 扫描进行中 |
| 95006 | CLONE_SOURCE_API_FAILED | 拉取 B 店数据失败 |
| 95007 | CLONE_PENDING_NOT_FOUND | 待审核记录不存在 |
| 95008 | CLONE_PENDING_INVALID_STATUS | 状态不允许该操作 |
| 95009 | CLONE_PUBLISH_FAILED | 上架到 A 平台失败 |
| 95010 | CLONE_CATEGORY_MAPPING_MISSING | 类目映射缺失 |
| 95011 | CLONE_TARGET_SHOP_INACTIVE | 目标店铺未激活 |

常量定义位置：`app/utils/errors.py`

---

## 8. AI 改写复用约定

**严格要求**：克隆模块**不重复实现** AI 改写，必须复用 SEO 模块现成接口。这样 SEO 规则未来改进，克隆自动同步受益。

| 用途 | 复用接口 | 调用约定 |
|---|---|---|
| 标题 AI 改写 | `app.services.product.service.optimize_title(db, listing_id, tenant_id)` | 必须先 INSERT 草稿 listing 拿到 listing_id |
| 描述 AI 改写 | `app.services.product.service.generate_description(db, listing_id, tenant_id, target_platform)` | 同上 |

**调用时机**：在 `_run_scan` 步骤 4.f / 4.g（详见 §4.1）

**草稿 listing 入库约定**：
```python
draft = PlatformListing(
    tenant_id=task.tenant_id,
    shop_id=task.target_shop_id,
    product_id=...,             # 同步 INSERT 一条 products 记录或复用
    platform=target_platform,
    platform_sku_id=f"clone-draft-{uuid4().hex[:8]}",  # 占位，发布后改真实 SKU
    title_ru=source.title_ru,
    description_ru=source.description_ru,
    status='inactive',
    clone_task_id=task.id,
    created_at=utc_now_naive(),
)
```

---

## 9. 类目映射兜底约定

**复用 028 表**：`local_categories` / `category_platform_mappings` / `attribute_mappings` / `attribute_value_mappings`

### 9.1 同平台（`source.platform == target.platform`）

直接复用 `source.platform_category_id` → 写入 proposed_payload，零映射工作。

### 9.2 跨平台

```
1. 从 category_platform_mappings 查 platform=source_platform AND platform_category_id=source.cat_id
   → 拿到 local_category_id
2. 反查 platform_platform_mappings WHERE local_category_id=X AND platform=target_platform
   → 拿到 target.platform_category_id
3. 任意一步失败 → 按 task.category_strategy 处理：
   a. reject_if_missing → 跳过该商品 + 记 skip_category_missing
   b. use_local_map → 同 a（Phase 1 不做 AI 兜底，避免错误克隆）
4. 属性映射类似流程，attribute_mappings + attribute_value_mappings
```

**Phase 1 不做 AI 类目兜底**：避免错误映射上架被平台拒。引导用户先用映射管理（`app/api/v1/category_mapping.py`）建好映射再启用克隆任务。

---

## 10. 数据库表对照

| 表 | 用途 | 迁移 |
|---|---|---|
| `clone_tasks` | 克隆任务（A ← B 关系 + 配置） | 062 |
| `clone_pending_products` | 待审核商品队列 | 062 |
| `clone_logs` | 克隆日志 | 062 |
| `clone_published_links` | 已发布关系（追溯 + 跟价） | 062 |
| `platform_listings` | + `clone_task_id` 字段 | 061 |

迁移文件：
- `database/migrations/versions/061_platform_listings_clone_task_id.sql`
- `database/migrations/versions/062_store_clone_tables.sql`

---

## 11. 后端文件分工（老张）

| 文件 | 职责 |
|---|---|
| `app/models/clone.py` | ORM 模型：CloneTask / ClonePendingProduct / CloneLog / ClonePublishedLink |
| `app/schemas/clone.py` | Pydantic 请求/响应模型 |
| `app/services/clone/providers/base.py` | `BaseShopProvider` 抽象 + `ProductSnapshot` |
| `app/services/clone/providers/seller_api.py` | Phase 1 实现（按平台分文件子模块：ozon.py / wb.py / yandex.py） |
| `app/services/clone/scan_engine.py` | `_run_scan(task_id)` + 类目映射检查 + 价格规则 |
| `app/services/clone/publish_engine.py` | `_publish_pending(pending_id)` + A 平台调用 |
| `app/services/clone/price_sync.py` | `follow_price_change` 跟价逻辑 |
| `app/services/clone/task_service.py` | CRUD + 启用/停用/scan-now 业务逻辑 |
| `app/tasks/clone_tasks.py` | Celery 任务：`daily_scan_all_tasks` / `publish_approved_pending` |
| `app/api/v1/clone.py` | API 路由（本文档所有接口） |

### 11.1 接口与函数映射

| 接口 | 函数 |
|---|---|
| POST /tasks | `task_service.create_task` |
| GET /tasks | `task_service.list_tasks` |
| GET /tasks/{id} | `task_service.get_task_detail` |
| PUT /tasks/{id} | `task_service.update_task` |
| POST /tasks/{id}/enable | `task_service.enable_task` |
| POST /tasks/{id}/disable | `task_service.disable_task` |
| POST /tasks/{id}/scan-now | `scan_engine._run_scan` |
| GET /pending | `task_service.list_pending` |
| POST /pending/{id}/approve | `task_service.approve_pending` |
| POST /pending/{id}/reject | `task_service.reject_pending` |
| PUT /pending/{id} | `task_service.update_pending_payload` |
| POST /pending/approve-batch | `task_service.batch_approve` |
| GET /logs | `task_service.list_logs` |
| GET /available-shops | `task_service.list_available_shops` |
| GET /category-coverage/{id} | `task_service.check_category_coverage` |

---

## 12. 前端契约（小明）

主菜单：**店铺克隆**（路径建议 `/clone`）

子页 3 个：

### 12.1 克隆任务（含配置）

- 路径：`/clone/tasks`
- 列表：每行一个任务（A 店 ← B 店 + 状态 + 最近扫描数据）
- 操作：新建 / 编辑 / 启用-停用 / 立即扫描 / 删除
- 新建按钮 → 模态向导：
  1. 选 A 店（available-shops dropdown）
  2. 选 B 店（同 dropdown，过滤掉 A 自己）
  3. 配置标题/描述/价格/类目策略
  4. 提交 → 调 POST /tasks（默认 is_active=false，让用户先验证再启用）
- 跨平台时显示「**跨平台克隆需要类目映射**」warning，给「检查映射覆盖率」按钮（调 GET /category-coverage）

### 12.2 待审核商品（主战场，每天打开）

- 路径：`/clone/pending`
- 顶部 task 切换 + status 切换（pending / failed / published 历史）
- 卡片视图：左侧 B 商品原图 + 标题 + 价 + 描述；右侧 proposed_payload 改写后预览（标 AI 改写过的字段）
- 行内编辑：点击字段直接改 proposed（调 PUT /pending/{id}）
- 批量勾选 + 批量批准/拒绝按钮
- 类目映射缺失的商品标红 warning，引导用户去"映射管理"页

### 12.3 克隆日志

- 路径：`/clone/logs`
- 时间线 / 表格切换
- 展开 detail JSON 看跳过的 SKU 列表 + 原因

---

## 13. 安全 / 多租户 / 时间字段自查清单

实现完成后必须 grep 通过：

```bash
# 规则 1：tenant_id 过滤
grep -rn "WHERE.*shop_id.*=.*:shop_id" app/services/clone app/api/v1/clone.py
# 上述每行必须紧跟 AND tenant_id=:tenant_id

# 规则 4：手动触发按 shop/task 过滤
grep -n "@router\." app/api/v1/clone.py | wc -l
# 应该 ≈ Depends(get_owned_shop) + 不需要 shop 的接口数（如 /pending 列表按 task_id）

# 规则 6：时间字段
grep -rn "datetime\.now\b\|datetime\.utcnow\|NOW()\|CURRENT_TIMESTAMP" app/services/clone app/tasks/clone_tasks.py
# 只允许 CREATE TABLE 里的 DEFAULT，业务代码必须用 utc_now_naive()
```

---

## 14. 版本历史

| 日期 | 版本 | 作者 | 变更 |
|---|---|---|---|
| 2026-05-02 | v1 | 老林 | 初稿：Phase 1 自营双店克隆 + Phase 2 公开 API 留口 + 4 张新表 + 1 个 ALTER |
