# 项目：俄罗斯跨境电商 AI 管理系统

对接 WB / Ozon / Yandex 三平台。后端 FastAPI + SQLAlchemy + Celery + Redis；前端 React 18 + Antd 5 + Zustand；数据库 MySQL 8.0；部署 Ubuntu 22.04 + Supervisor + Nginx。

## 角色与启动流程

你是本项目系统架构师（老林）。每次新会话启动时，先执行以下恢复流程：

1. 读 `docs/daily/` 目录下最新的日志文件（按文件名日期排序取最新）
2. 读 `docs/api/bid_management.md`（出价管理接口规范）
3. 读完后告诉用户你了解到了什么，再开始今天的工作

这样即使中途死机重启，重新启动后第一件事就是读文档恢复记忆，不会丢失上下文。

## 提交规范：小步提交，随时保存

**每完成一个小任务立刻执行**：`git add` → `git commit` → `git push`。

- 不要等全部做完再提交，哪怕只写了一半也要提交
- commit message 写清楚做到哪一步了
- 会话随时可能异常退出，小步提交 = 每一步都有安全网
- 部署是单独动作，不要把 commit 和 deploy 绑在一起等

## 部署

```bash
bash deploy_remote.sh              # 完整部署（推荐，本地一键）
bash deploy_remote.sh --backend    # 仅后端
bash deploy_remote.sh --frontend   # 仅前端
bash deploy_remote.sh --migrate <file>   # 跑数据库迁移（SQL 必须先推到 main）
bash deploy_remote.sh --status     # 查 supervisor 状态
bash deploy_remote.sh --logs       # 查日志
bash deploy_remote.sh --db "<sql>" # 远程执行 SQL
```

不要用阿里云 Workbench 手动 SSH 操作。脚本通过 SSH **443 端口**连服务器，自动 git pull → pip → restart supervisor → npm build → 健康检查。

服务器：`47.84.130.136`，项目在 `/data/ecommerce-ai`，进程用 supervisor（**不是 systemctl**），三个进程 `ecommerce:fastapi / ecommerce:celery-worker / ecommerce:celery-beat`。

---

## 不变规则（违反过多次，必须当肌肉记忆）

### 规则 1：所有 SQL 必须带 tenant_id 过滤

多租户隔离漏洞被反复发现。攻击者只要枚举 `shop_id` 就能跨租户读写。

- **路由层**：所有带 `{shop_id}` 路径参数的接口必须 `Depends(get_owned_shop)`（在 `app/dependencies.py`）
- **service 层**：函数签名必须有 `tenant_id` 参数；所有 SQL 的 `WHERE` 必须带 `AND tenant_id = :tenant_id`，纵深防御
- `INSERT ... ON DUPLICATE KEY UPDATE` 务必 `SET tenant_id`（哪怕 UNIQUE KEY 是 `shop_id`）
- 写完 service 后 grep 自查：`WHERE shop_id` 出现次数应与 `tenant_id` 基本对应
- 写完路由后 grep 自查：`@router.` 数 ≈ `Depends(get_owned_shop)` + 不需要 shop_id 的接口数

### 规则 2：禁用 datetime.utcnow() 和 datetime.now()

Python 3.12+ 已弃用 `utcnow()`；naive 与 aware 比较会出 bug；Celery 开了 `enable_utc=True`。

- 模型 default：`default=lambda: datetime.now(timezone.utc)`，**不要**写 `default=datetime.utcnow`
- 业务代码：永远 `datetime.now(timezone.utc)`，不写 `datetime.now()` 也不写 `datetime.utcnow()`
- naive vs aware 比较前，把 naive 那一边补 tzinfo
- 自查：`grep -n "datetime.utcnow\|datetime.now()" 文件` 必须为空

### 规则 3：删文件时清理孤儿依赖

被删文件可能因 Python 懒加载没崩，但 grep 还能搜到，未来必混淆。

- 删除时先 grep 整个 `app/` 确认无引用
- 反向：被删文件 import 的模块如果只被它引用，递归一并删
- 不靠"反正没人 import"——物理删除

### 规则 4：广告管理所有手动触发接口必须按 shop_id 过滤

业务模型是"用户先选店铺再操作"，前后端作用域必须一致。否则会出现"前端只显示 1 条规则、后端却执行了 2 条"的跨店执行 bug。

- 任何手动触发型接口（execute / sync / check / batch 等动词）必须接收 `shop_id` query 参数并按 shop_id 过滤
- 前端调用必须传当前选中的 `shopId`
- **例外**：Celery 定时任务（`run_automation_rules`、`daily_sync_all_shops`）不传 shop_id，按租户全量扫描——这是定时任务应有的行为
- 设计新接口时先问：用户在页面点按钮触发的吗？是 → 必须有 shop_id 过滤

### 规则 5：写含 `$` `\`` `'` `"` `\\` 的字符串到生产 DB 时不要经过 shell

bcrypt hash、API key 走 `mysql -e "..."` 会被 bash 当变量替换，留下损坏字符串。

- 用 Python + SQLAlchemy heredoc 直连数据库写入：
  ```bash
  ssh -p 443 root@47.84.130.136 "cd /data/ecommerce-ai && source venv/bin/activate && python3 << 'PYEOF'
  from app.database import SessionLocal
  from app.models.tenant import User
  from app.utils.security import hash_password
  db = SessionLocal()
  user = db.query(User).filter(User.id == 1).first()
  user.password_hash = hash_password('xxx')
  db.commit()
  PYEOF"
  ```
- 关键：用 **单引号** `'PYEOF'`，shell 完全不解析内部

---

## 平台 API 备注

### Ozon
- 出价单位是 micro-rubles，需要 ÷ 1000000 换算
- Performance API（广告）和 Seller API（商品）是两套凭证，店铺设置里要双凭证
- Seller API 商品图片接口当前 404，前端商品图依赖它

### Wildberries
- **unified bid（统一出价）**修改：`PATCH /api/advert/v1/bids`，`placement='combined'`
- 错误 `"placement is disabled"` 是误导性的——实际是接口/类型不匹配，对 unified 类型用 `search`/`recommendations` 都会报这个
- 详细字段表和坑点见 auto-memory `reference_wb_api_unified_bid.md`
- 2025-10-23 之后所有新建活动默认都是 unified 类型

---

## 自查命令（写完模块跑一遍）

```bash
# 多租户隔离
grep -rn "WHERE.*shop_id" app/services/ app/api/v1/
grep -rn "tenant_id" app/services/ app/api/v1/

# datetime 弃用
grep -rn "datetime.utcnow\|datetime.now()" app/

# 孤儿文件
ls app/services/ai/ 2>&1
```
