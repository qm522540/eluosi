from fastapi import APIRouter

from app.api.v1 import system, auth, shops

api_router = APIRouter()

# 系统（无需认证的健康检查优先注册）
api_router.include_router(system.router, prefix="/system", tags=["系统"])

# 认证（登录/注册无需JWT）
api_router.include_router(auth.router, prefix="/auth", tags=["认证"])

# 店铺管理
api_router.include_router(shops.router, prefix="/shops", tags=["店铺"])

# 后续模块在开发时逐个注册:
# from app.api.v1 import products, ads, seo, inventory, finance
# api_router.include_router(products.router, prefix="/products", tags=["商品"])
# api_router.include_router(ads.router, prefix="/ads", tags=["广告"])
# api_router.include_router(seo.router, prefix="/seo", tags=["SEO"])
# api_router.include_router(inventory.router, prefix="/inventory", tags=["库存"])
# api_router.include_router(finance.router, prefix="/finance", tags=["财务"])
