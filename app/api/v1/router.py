from fastapi import APIRouter

from app.api.v1 import system, auth, shops, products, ads, finance, notifications, bid_management, category_mapping, keyword_stats, region_stats, search_insights, seo

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

# 出价管理（分时调价 + AI调价 统一入口）
api_router.include_router(bid_management.router, prefix="/bid-management", tags=["出价管理"])

# 映射管理（本地分类 + 品类/属性/属性值映射）
api_router.include_router(category_mapping.router, prefix="/mapping", tags=["映射管理"])

# 关键词统计
api_router.include_router(keyword_stats.router, prefix="/keyword-stats", tags=["关键词统计"])

# 地区销售统计
api_router.include_router(region_stats.router, prefix="/region-stats", tags=["地区销售"])

# 搜索词洞察（SEO 流量分析，需 Jam / Premium 订阅）
api_router.include_router(search_insights.router, prefix="/search-insights", tags=["搜索词洞察"])

# SEO 优化（付费词反哺自然词 + 多源融合候选池）
api_router.include_router(seo.router, prefix="/seo", tags=["SEO优化"])

# 后续模块:
# from app.api.v1 import inventory
# api_router.include_router(inventory.router, prefix="/inventory", tags=["库存"])
