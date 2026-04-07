# 俄罗斯电商AI自动化运营系统

## 项目定位
面向俄罗斯跨境电商卖家的AI运营操作系统。
支持 Wildberries / Ozon / Yandex Market 三平台统一管理，
AI驱动广告投放优化、SEO内容生成、库存采购、财务分析，
最终面向多品牌多店铺SaaS商业化输出。

## 技术栈
- 后端：Python 3.11 + FastAPI
- 数据库：MySQL 8.0（ECS本地部署）
- 缓存/队列：Redis + Celery
- AI：DeepSeek（分析）/ Kimi（长文档）/ GLM（俄语文案）
- 通知：企业微信群机器人 + 应用消息
- 前端：React + Ant Design
- 部署：阿里云ECS Ubuntu 22.04
- 代码管理：GitHub

## 团队角色
| 角色 | 负责范围 |
|------|---------|
| PM（你） | 需求决策·验收·方向把控 |
| 架构师 | 数据库·API设计·技术规范 |
| 后端开发 | 业务逻辑·AI集成·接口实现 |
| 数据工程师 | 平台数据采集·清洗·调度 |
| 前端开发 | 仪表盘·可视化·企业微信 |

## 分支规范
- main：生产环境，只接受合并请求
- dev：开发主分支，每日合并
- feature/xxx：功能分支，完成后合并到dev

## 目录结构
ecommerce-ai/
├── app/
│   ├── api/          # FastAPI路由
│   ├── models/       # 数据库模型
│   ├── services/
│   │   ├── ad/       # 广告模块
│   │   ├── seo/      # SEO模块
│   │   ├── inventory/# 库存模块
│   │   ├── product/  # 商品模块
│   │   ├── finance/  # 财务模块
│   │   └── ai/       # AI决策路由
│   ├── tasks/        # Celery定时任务
│   └── utils/        # 工具函数
├── database/
│   └── migrations/
├── frontend/         # React前端
├── docs/             # 接口文档
├── tests/
└── CLAUDE.md         # 各角色规范