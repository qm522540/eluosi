# 映射管理模块 API 接口规范

> 模块：Category Mapping（本地统一分类 + 三层映射：品类 / 属性 / 属性值）
> 前缀：`/api/v1/mapping`
> 平台范围：WB / Ozon（Yandex 预留）
> 认证：所有接口需携带 `Authorization: Bearer <token>`
> 后端：老张
> 前端：小明
> 版本：v1（2026-04-16）

---

## 0. 业务背景

**为什么要有映射管理？**
铺货场景下，同一件商品要发到 WB、Ozon、Yandex 三个平台，但每个平台的分类体系、属性定义、属性枚举值都完全不同：

- WB 用 `subjectID`（扁平结构）
- Ozon 用 `description_category_id` + `type_id`（三级树）
- Yandex 又是另一套

如果每次铺货都手动选目标平台的分类和属性，效率太低。所以做一套**"本地统一分类 → 各平台分类/属性/属性值"**的映射体系。

**设计核心：AI 推荐 + 人工确认**
- AI 自动推荐映射关系（给置信度）
- 用户前端逐条人工确认或修改（防止 AI 映射错了生产出错）
- 每条映射带 `ai_suggested` / `ai_confidence` / `is_confirmed` 三个字段

---

## 1. 业务流程

### 推荐流程（一键初始化，2026-04-16 v2）

```
① 从 WB 初始化         ② 从 Ozon 扩充          ③ 人工确认 Ozon 侧
   ↓                     ↓                       ↓
本地分类+属性+枚举值      Ozon 独有分类新增        逐条核对修改
(自动确认 WB 侧)          Ozon 共通分类合并映射
                         (Ozon 侧 待确认)
```

- 入口按钮 `[从 WB 初始化]` + `[从 Ozon 扩充]`（+ 备用 `[AI 匹配 Ozon]`）
- 详见 §7.4 / §7.5 / §7.6

**设计思想**：以 WB 作为本地分类的种子（中文名由 AI 翻译），然后 Ozon
智能合并——OZON 有 WB 对应分类的直接建映射，没有的新建本地分类。
两个平台共用同一套本地分类树。

### 手动流程（备用，适合新增零散分类）

```
① 建本地分类 → ② 品类映射 → ③ 属性映射 → ④ 属性值映射
```

**① 建本地分类**（用户手动创建，中俄文双名）
```
首饰
├── 项链
├── 手链
└── 耳环
```

**② 品类映射**（本地分类 → 各平台分类，一对多）
```
本地"项链"
├── WB subjectID=123 "Ожерелья"   [AI推荐 置信度95%  已确认 ✓]
└── Ozon type_id=456 "Колье"       [AI推荐 置信度80%  待确认 ⚠]
```

**③ 属性映射**（本地属性 → 各平台属性，按分类绑定）
```
本地分类"项链" 下的属性：
  "材质" → WB "Материал"(charcID=10) 必填  [AI置信度90% ✓]
         → Ozon "Материал изделия"(attr_id=20) 必填  [AI置信度85% ✓]
  "长度" → WB "Длина цепи"  可选
         → Ozon "Длина"      可选
```

**④ 属性值映射**（本地属性值 → 平台枚举字典值，针对 enum 类型的属性）
```
属性"材质" 的值映射：
  本地"925银"  → WB dict_id=11 "Серебро 925 пробы"  ✓
                → Ozon dict_id=22 "Серебро"              ✓
  本地"18K金"  → WB dict_id=12 "Золото 585"              ✓
                → Ozon dict_id=23 "Золото"                ✓
```

---

## 2. 通用约定

### 2.1 响应格式（同项目统一规范）
```json
{ "code": 0, "msg": "success", "data": {}, "timestamp": 1744300800 }
```

### 2.2 AI 推荐 + 人工确认状态机

每条映射记录都有三个关键字段：

| 字段 | 类型 | 含义 |
|---|---|---|
| `ai_suggested` | 0/1 | 1 = AI 推荐生成，0 = 用户手动创建 |
| `ai_confidence` | 0-100 | AI 置信度，供前端着色提示 |
| `is_confirmed` | 0/1 | 0 = 待确认（橙色），1 = 已人工确认（绿色） |

**前端渲染建议**：
- `is_confirmed=0 && ai_confidence >= 80` → 橙色徽章 "AI推荐 高置信"
- `is_confirmed=0 && ai_confidence < 80` → 红色徽章 "AI推荐 请核对"
- `is_confirmed=1` → 绿色徽章 "已确认"

---

## 3. 本地分类接口

### 3.1 列表（按父分类过滤）

**GET** `/api/v1/mapping/local-categories?parent_id={id}`

- `parent_id=0` → 只返回顶级
- `parent_id=5` → 返回 id=5 的子分类
- 不传 → 返回全部（扁平）

**响应 data.items[]**：
```json
{
  "id": 1,
  "parent_id": null,
  "name": "首饰",
  "name_ru": "Украшения",
  "level": 1,
  "sort_order": 0,
  "status": "active",
  "created_at": "2026-04-16T08:00:00Z"
}
```

### 3.2 完整树

**GET** `/api/v1/mapping/local-categories/tree`

返回 `data.tree[]` 嵌套结构（`children[]`），前端可直接喂 Antd `<Tree>` 组件。

### 3.3 新建

**POST** `/api/v1/mapping/local-categories`
```json
{ "name": "项链", "name_ru": "Ожерелья", "parent_id": 1, "sort_order": 0 }
```
- `parent_id` 为 null = 顶级
- `name` 必填，中文
- `name_ru` 可选，AI 推荐映射时会用

**约束**：分类最多 3 级，第 4 级返回 `10002`

### 3.4 修改

**PUT** `/api/v1/mapping/local-categories/{cat_id}`
```json
{ "name": "银项链", "name_ru": "Серебряные ожерелья", "sort_order": 1 }
```

### 3.5 删除

**DELETE** `/api/v1/mapping/local-categories/{cat_id}`

- 先检查没有子分类（有子分类返回 `10002`）
- 同时级联删除该分类下所有品类映射
- 软删除（`status=inactive`）

---

## 4. 品类映射接口

### 4.1 列表

**GET** `/api/v1/mapping/category-mappings?local_category_id=1&platform=wb&is_confirmed=0`

三个查询参数都可选，全部不传 = 返回租户全部映射。

**响应 data.items[]**：
```json
{
  "id": 10,
  "local_category_id": 1,
  "platform": "wb",
  "platform_category_id": "123",
  "platform_category_extra_id": null,
  "platform_category_name": "Ожерелья",
  "platform_parent_path": "Украшения > Ожерелья",
  "ai_suggested": 1,
  "ai_confidence": 95,
  "is_confirmed": 0,
  "confirmed_at": null,
  "created_at": "2026-04-16T08:10:00Z"
}
```

**字段说明**：
- `platform_category_id`：WB=subjectID / Ozon=description_category_id
- `platform_category_extra_id`：仅 Ozon 使用，存 type_id。WB 场景为 null

Ozon 示例：
```json
{
  "platform": "ozon",
  "platform_category_id": "17028922",
  "platform_category_extra_id": "93080",
  "platform_category_name": "Колье и бусы"
}
```

### 4.2 新建 / 修改（upsert）

**POST** `/api/v1/mapping/category-mappings`
```json
{
  "local_category_id": 1,
  "platform": "wb",
  "platform_category_id": "123",
  "platform_category_name": "Ожерелья",
  "platform_parent_path": "Украшения > Ожерелья"
}
```

- 按 `(tenant_id, local_category_id, platform)` 唯一键 upsert
- 同一本地分类在同一平台只能有一个映射

### 4.3 人工确认（支持同时修改）

**POST** `/api/v1/mapping/category-mappings/{mapping_id}/confirm`

**请求体**（可选，只传想修改的字段）：
```json
{
  "platform_category_id": "124",
  "platform_category_name": "新分类名"
}
```

空 body 表示"不改映射值，只确认"。

执行后 `is_confirmed=1 + confirmed_at=now`。

### 4.4 删除

**DELETE** `/api/v1/mapping/category-mappings/{mapping_id}`

---

## 5. 属性映射接口

### 5.1 列表

**GET** `/api/v1/mapping/attribute-mappings?local_category_id=1&platform=wb`

`local_category_id` **必填**，`platform` 可选。

**响应 data.items[]**：
```json
{
  "id": 100,
  "local_category_id": 1,
  "local_attr_name": "材质",
  "local_attr_name_ru": "Материал",
  "platform": "wb",
  "platform_attr_id": "10",
  "platform_attr_name": "Материал",
  "is_required": 1,
  "value_type": "enum",
  "platform_dict_id": "500",
  "ai_suggested": 1,
  "ai_confidence": 90,
  "is_confirmed": 0
}
```

`value_type` 取值：`string / enum / number / boolean`
`platform_dict_id` 非空 → 该属性是枚举类型，有对应的字典值映射

### 5.2 新建 / 修改

**POST** `/api/v1/mapping/attribute-mappings`
```json
{
  "local_category_id": 1,
  "local_attr_name": "材质",
  "local_attr_name_ru": "Материал",
  "platform": "wb",
  "platform_attr_id": "10",
  "platform_attr_name": "Материал",
  "is_required": 1,
  "value_type": "enum",
  "platform_dict_id": "500"
}
```

唯一键：`(tenant_id, local_category_id, local_attr_name, platform)`

### 5.3 确认 / 删除

**POST** `/api/v1/mapping/attribute-mappings/{mapping_id}/confirm`（body 可选）
**DELETE** `/api/v1/mapping/attribute-mappings/{mapping_id}`

删除属性映射会级联删除该属性下所有属性值映射。

---

## 6. 属性值映射接口

### 6.1 列表

**GET** `/api/v1/mapping/attribute-value-mappings?attribute_mapping_id=100`

`attribute_mapping_id` **必填**。

**响应 data.items[]**：
```json
{
  "id": 1000,
  "attribute_mapping_id": 100,
  "local_value": "925银",
  "local_value_ru": "Серебро 925",
  "platform_value": "Серебро 925 пробы",
  "platform_value_id": "11",
  "ai_suggested": 1,
  "ai_confidence": 92,
  "is_confirmed": 0
}
```

### 6.2 新建 / 修改 / 确认 / 删除

- **POST** `/api/v1/mapping/attribute-value-mappings`
- **POST** `/api/v1/mapping/attribute-value-mappings/{mapping_id}/confirm`
- **DELETE** `/api/v1/mapping/attribute-value-mappings/{mapping_id}`

唯一键：`(attribute_mapping_id, local_value)`

---

## 7. AI 辅助映射推荐

### 7.1 AI 推荐品类映射

**POST** `/api/v1/mapping/ai-suggest/category`
```json
{
  "local_category_id": 1,
  "platforms": ["wb", "ozon"],
  "shop_id": 5
}
```

`shop_id` 用于取该店铺的凭证去拉平台全量分类列表（所以映射可以跨所有租户分类共享结果）。

**响应 data.suggestions[]**：
```json
[
  {
    "platform": "wb",
    "id": "123",
    "name": "Ожерелья",
    "path": "Украшения > Ожерелья",
    "confidence": 95,
    "reason": "本地分类'项链'的俄文Ожерелья与WB候选完全一致"
  },
  {
    "platform": "ozon",
    "error": "拉取平台分类失败"
  }
]
```

后端已把推荐结果**自动写入 `category_platform_mappings`**（`ai_suggested=1, is_confirmed=0`），前端重新拉 §4.1 列表即可看到。

**前端交互建议**：
1. 用户在本地分类上点"AI 推荐映射"
2. 弹窗选平台（WB / Ozon / 全部）+ 选关联的店铺
3. Loading...（后端会调 AI + 平台 API，通常 5-15 秒）
4. 完成后刷新右侧映射列表，标橙色"AI 推荐，待确认"

### 7.2 AI 推荐属性映射

**POST** `/api/v1/mapping/ai-suggest/attributes`
```json
{
  "local_category_id": 1,
  "platform": "wb",
  "shop_id": 5
}
```

**前置条件**：该本地分类在该平台上必须**已经有品类映射**（无论是否确认），否则返回 `10002 请先完成品类映射`。

**响应 data**：
```json
{ "count": 18 }
```

后端批量写入 18 条属性映射，AI 按俄文属性名自动推荐中文本地属性名。前端刷新 §5.1 列表。

### 7.3 AI 推荐属性值映射

**POST** `/api/v1/mapping/ai-suggest/values`
```json
{
  "attribute_mapping_id": 100,
  "local_values": ["925银", "18K金", "合金"],
  "shop_id": 5
}
```

**前置条件**：
- 属性映射的 `value_type` 必须是 `enum`（非枚举类型报 `10002`）
- 该属性对应的品类映射必须存在（否则报 `10002 请先完成品类映射`）

**响应 data**：
```json
{ "count": 3, "total": 3 }
```

`count` = AI 成功匹配的数量，`total` = 请求的本地值总数。未匹配到的跳过（不写入）。

后端流程：
1. 查属性映射拿 `platform_attr_id` + `value_type`
2. 查品类映射拿 `platform_category_id` + `extra_id`
3. 拉平台字典值（WB 从 charcs 的 dictionary 字段，Ozon 调 attribute/values）
4. AI 按本地值的顺序，为每个值匹配 top-1 枚举候选 + 置信度
5. 批量 upsert 到 `attribute_value_mappings`，`ai_suggested=1`

**前端交互建议**：
- 在属性值映射 Drawer 底部加"AI 推荐"按钮
- 用户先输入/粘贴一组本地值（如"925银\n18K金\n合金"），点按钮触发
- Loading...（5-15 秒）
- 完成后刷新 §6.1 列表，未确认的标橙色

---

### 7.4 一键从 WB 初始化（推荐入口）

**POST** `/api/v1/mapping/init-from-wb`

```json
{
  "shop_id": 5,
  "include_enum_values": true
}
```

**业务流程**：
1. 从 `platform_listings` 反查店铺已出现的 WB `subjectID` 集合
2. 拉 WB `/content/v2/object/all` 全量分类字典，筛出店铺用到的
3. 批量 AI 翻译俄文 `subjectName` → 中文
4. 建 `local_categories`（level=1）
5. 自动建 WB `category_platform_mappings`，**直接 `is_confirmed=1`**（1:1 关联无需人工确认）
6. 对每个分类拉 `charcs` 属性列表，翻译后建 `attribute_mappings`（同样自动确认）
7. 如 `include_enum_values=true`，属性的 `dictionary` 字段内枚举值也批量翻译后写入 `attribute_value_mappings`

**响应 data**：
```json
{
  "categories": 20,
  "attributes": 180,
  "values": 650,
  "skipped": ["本地分类已存在: Ожерелья", "charcs 拉取失败: 8765"]
}
```

**注意**：
- 如果 `platform_listings` 里该店铺没有任何分类数据（`platform_category_id` 全为空），返回 `10002 请先同步商品`
- 已存在的本地分类（按 `name_ru` 去重）会跳过不覆盖
- 耗时 **30-120 秒**（视分类数量），前端必须加 Loading 态

**前端交互建议**：
- 在映射管理页顶部放大按钮 `[从 WB 初始化]`
- 弹窗选 WB 店铺 + 是否包含枚举值（默认勾选）
- 确认弹窗提示："这将从 WB 店铺拉取分类和属性，预计 1-2 分钟。是否继续？"
- Loading 期间不可关闭，显示进度提示"正在抓取分类..."/"正在翻译..."/"正在建立映射..."（可能只是静态文案，后端不回报进度）

### 7.5 一键从 Ozon 扩充本地分类（推荐入口 2）

**POST** `/api/v1/mapping/init-from-ozon`

```json
{
  "shop_id": 6,
  "include_enum_values": true
}
```

**前置条件**：OZON 店铺已同步过商品（`platform_listings.platform_category_id`
有数据）。否则返回 `10002 请先同步 Ozon 商品`。

**业务流程**：
1. 从 `platform_listings` 反查 OZON 店铺已用的 `description_category_id`
2. 对每个 `description_category_id`：
   - 从该分类下任一商品反查 `type_id`（OZON 发布必需的第二个 ID）
   - 从分类树反查完整名称+面包屑路径
3. **AI 归一去重**：一次调用把所有 OZON 分类 + 已有本地分类给 AI，
   让 AI 判断每个 OZON 分类对应哪个本地 idx（或 null=无对应）
4. 对每个 OZON 分类：
   - **AI 认为已有对应** → 只建 OZON 品类映射 `is_confirmed=0`（待用户确认）
   - **AI 认为无对应** → 新建本地分类（翻译中文）+ OZON 品类映射
     `is_confirmed=1`（1:1 直接关联）
5. 对每个 OZON 分类拉属性：
   - 同样做"同名复用"：本地已有同名属性（WB 种子带来的）→ 复用 `local_attr_name`
     只新增 Ozon platform 的映射行
   - 本地没有的新属性名 → 新建
6. 枚举值同步翻译写入（每个属性最多 200 条）

**响应 data**：
```json
{
  "categories_new": 1,
  "categories_merged": 1,
  "attributes_new": 79,
  "attributes_reused": 1,
  "values": 0,
  "skipped": []
}
```

**实测样例（shop_id=2 OZON-Shario, 2 个唯一分类）**：
- 1 个分类 AI 合并到已有本地"气球"（OZON 的"Воздушные шары" ≈ WB 的"Воздушные шарики"）
- 1 个新建本地分类"时尚饰品（Бижутерные украшения）"
- 79 条新本地属性 + 1 条复用 WB 已有属性名

**耗时**：40-180 秒（视分类数量）

**前端交互建议**：
- 顶部第二个按钮 `[从 Ozon 扩充]`
- 点之前先判 WB 已初始化（否则提示"建议先从 WB 初始化"——但允许继续）
- 弹窗：选 Ozon 店铺 + 是否含枚举值
- Loading 文案："正在反查 Ozon 分类信息..." / "AI 归一去重中..." / "建立映射..."
- 完成后引导用户切到"待确认"筛选（橙色那些就是 AI 推荐的 Ozon 归一）

### 7.6 AI 批量匹配 Ozon（备用）

**POST** `/api/v1/mapping/match-ozon`

```json
{ "shop_id": 6 }
```

**前置条件**：
- 本地分类已经存在（通过 §7.4 初始化或手动创建）
- 本地分类为空时返回 `10002 请先从 WB 初始化`

**业务流程**：
1. 遍历所有本地分类
2. 每个分类调 `suggest_category_mappings(platforms=['ozon'])`（§7.1）
3. 对每个成功匹配的分类再调 `suggest_attribute_mappings('ozon')`（§7.2）
4. 所有新建映射 **`is_confirmed=0`**（等待用户在前端逐条确认）

**响应 data**：
```json
{
  "categories": { "matched": 18, "failed": 2 },
  "attributes": { "matched": 142, "failed": 3 }
}
```

**耗时**：60-300 秒（每个分类约 5-15 秒 AI 调用）

**与 §7.5 的区别**：
- §7.5 `init-from-ozon` 会**扩充本地分类**（OZON 独有分类会新建本地分类）
- §7.6 `match-ozon` **只匹配已有本地分类**，不新建（纯"找对应"）
- 推荐流程用 §7.5。§7.6 作为备用，适合"本地分类体系由用户手工管理，只让 AI 补 Ozon 映射"的场景

**前端交互建议**：
- 顶部第三个按钮 `[批量匹配 Ozon（备用）]`（折叠或放三级菜单，避免混淆主流程）
- 或者根本不做按钮，在个别本地分类右键菜单里加"AI 匹配 Ozon"作为单条操作

---

## 8. 前端页面设计建议

### 8.1 入口位置

在左侧菜单"商品管理"下加二级菜单"映射管理"，路径 `/products/mapping`。

### 8.2 页面布局

```
┌─────────────────────────────────────────────────────────────────────┐
│  映射管理                                     [+ 新建本地分类] [AI推荐] │
├──────────────┬──────────────────────────────────────────────────────┤
│              │  右侧：Tab 三选一                                      │
│  左侧：       │  ┌──────────────────────────────────────────────────┐│
│  本地分类树   │  │ [品类映射] [属性映射] [属性值映射]                ││
│              │  ├──────────────────────────────────────────────────┤│
│  ▼ 首饰      │  │                                                   ││
│    ▼ 项链 ★  │  │  当前选中分类：项链                               ││
│      - 金项链 │  │                                                   ││
│    - 手链    │  │  平台     映射                  状态      操作    ││
│    - 耳环    │  │  ───      ──────────────        ────     ──────  ││
│  ▼ 服装      │  │  WB       Ожерелья (123)        ✓已确认  [改][删] ││
│    - 连衣裙  │  │           path: Украшения > ... AI: 95%           ││
│              │  │                                                   ││
│              │  │  Ozon     Колье (456)           ⚠待确认 [确认][改]││
│              │  │           path: Аксессуары > ...AI: 80%           ││
│              │  │                                                   ││
│              │  │  [+ 手动添加映射]   [AI 推荐映射]                  ││
│              │  │                                                   ││
│              │  └──────────────────────────────────────────────────┘│
└──────────────┴──────────────────────────────────────────────────────┘
```

### 8.3 关键交互

**A. 左侧分类树**
- Antd `<Tree>` 组件
- 右键菜单：新建子分类 / 重命名 / 删除
- 节点尾部小标 ★ 表示"至少有一个未确认的映射"（需前端自己算或后端加个字段，先不算也行）
- 数据：`GET /local-categories/tree`

**B. 右侧品类映射 Tab**
- 表格列：平台 / 平台分类 / 面包屑 / AI 置信度 / 状态 / 操作
- 操作列按钮：
  - 未确认：`[确认]` `[修改]` `[删除]`
  - 已确认：`[修改]` `[删除]`
- `[AI 推荐映射]` 按钮：弹窗选平台 + 店铺 → 调 §7.1 → Loading → 刷新列表

**C. 右侧属性映射 Tab**
- 表格列：平台 / 平台属性 / 本地属性名 / 必填 / 类型 / AI置信度 / 状态 / 操作
- 显示前先切换"平台"下拉（WB / Ozon），再点 `[AI 推荐]`
- 枚举类型（`value_type=enum`）的行右边多一个 `[管理值映射]` 按钮 → 打开 §8.4

**D. 属性值映射 Drawer**
- 从属性映射行的 `[管理值映射]` 打开右抽屉
- 表格列：本地值 / 平台值 / 置信度 / 状态 / 操作
- 底部 `[+ 手动添加]` 按钮（AI 推荐后期接入）

### 8.4 置信度可视化

```jsx
function ConfidenceBadge({ conf, confirmed }) {
  if (confirmed) return <Tag color="green">已确认</Tag>
  if (conf >= 80) return <Tag color="orange">AI {conf}% 请核对</Tag>
  if (conf >= 60) return <Tag color="red">AI {conf}% 请核对</Tag>
  return <Tag color="red">AI {conf}% 请仔细核对</Tag>
}
```

### 8.5 与商品管理页的联动（后续）

当商品管理页的"分类"列显示 `local_category_id` 对应的本地分类名时（需要前端 join 一次本地分类表），点击可跳转到映射管理，并自动选中该本地分类。

本期前端先做独立映射管理页，商品管理联动下轮再做。

---

## 9. Mock 数据参考

所有响应样例都可直接复用文档里的 JSON。建议的 mock 节奏：

1. 先把本地分类 CRUD 跑通（§3）
2. 品类映射 CRUD（§4）
3. AI 推荐品类（§7.1）—— 后端已在线，可直连真实接口测
4. 属性映射 + AI 推荐属性（§5 + §7.2）
5. 属性值映射（§6）
6. 迭代细节：置信度徽章、状态图标、Empty 态

---

## 10. 与小明现有工作的对接

- 当前商品管理页 `frontend/src/pages/Products.jsx` 的"分类"列是空的（老张 2026-04-16 已在同步时回填平台分类到 listing 级别，本地分类字段 `local_category_id` 要等有了映射管理页才能真正用上）
- 铺货弹窗当前是占位，未来真正铺货时会自动读这套映射数据（不需要小明改铺货弹窗）

---

## 11. 错误码

| code | 说明 |
|---|---|
| 0 | 成功 |
| 10002 | 参数错误（含：分类超过3级 / 有子分类不能删 / 枚举值映射仅支持enum类型 / 未完成品类映射） |
| 30001 | 店铺不存在（AI 推荐时传了无效 shop_id） |
| 99999 | 未知错误（AI调用失败 / 平台API失败等） |

---

## 12. 版本历史

| 日期 | 版本 | 作者 | 变更 |
|---|---|---|---|
| 2026-04-16 | v1 | 老张 | 初稿：本地分类 + 三层映射 + AI 推荐 |
