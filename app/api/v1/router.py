from fastapi import APIRouter

from app.api.v1 import system, auth, shops, products, ads, finance, notifications, tasks

api_router = APIRouter()

# 系统（无需认证的健康检查优先注册）
api_router.include_router(system.router, prefix="/system", tags=["系统"])

# 认证（登录/注册无需JWT）
api_router.include_router(auth.router, prefix="/auth", tags=["认证"])

# 店铺管理
api_router.include_router(shops.router, prefix="/shops", tags=["店铺"])

# 商品管理
api_router.include_router(products.router, prefix="/products", tags=["商品"])

# 广告管理
api_router.include_router(ads.router, prefix="/ads", tags=["广告"])

# 财务管理
api_router.include_router(finance.router, prefix="/finance", tags=["财务"])

# 通知管理
api_router.include_router(notifications.router, prefix="/notifications", tags=["通知"])

# 数据采集任务
api_router.include_router(tasks.router, prefix="/tasks", tags=["任务"])

# 后续模块:
# from app.api.v1 import seo, inventory
# api_router.include_router(seo.router, prefix="/seo", tags=["SEO"])
# api_router.include_router(inventory.router, prefix="/inventory", tags=["库存"])
