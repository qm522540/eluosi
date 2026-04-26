"""搜索词洞察路由（SEO 流量分析）

前缀：/api/v1/search-insights
平台：WB（需 Jam 订阅）/ Ozon（需 Premium 订阅）
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_tenant_id, get_owned_shop
from app.services.search_insights.service import (
    list_shop, list_by_product, refresh_shop,
)
from app.utils.response import success, error

router = APIRouter()


@router.get("/shop/{shop_id}")
def shop_summary(
    shop_id: int,
    date_from: str = Query(None),
    date_to: str = Query(None),
    keyword: str = Query(None),
    sort_by: str = Query("frequency"),
    sort_order: str = Query("desc"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=2000),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
):
    """店铺维度搜索词汇总（按 query_text 聚合）"""
    result = list_shop(
        db, tenant_id, shop.id, date_from, date_to,
        None, keyword, sort_by, sort_order, page, size,
    )
    if result.get("code") != 0:
        return error(result["code"], result.get("msg", ""))
    return success(result["data"])


@router.get("/product/{product_id}")
def product_detail(
    product_id: int,
    date_from: str = Query(None),
    date_to: str = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """单商品搜索词明细（编辑 Drawer Tab 用）"""
    result = list_by_product(db, tenant_id, product_id, date_from, date_to, page, size)
    if result.get("code") != 0:
        return error(result["code"], result.get("msg", ""))
    return success(result["data"])


@router.post("/shop/{shop_id}/refresh")
async def shop_refresh(
    shop_id: int,
    days: int = Query(30, ge=1, le=90, description="回看天数（默认 30，最多 90）"),
    force: bool = Query(False, description="强制重拉（清窗口内已有数据 + 全部重拉）"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
):
    """手动触发同步（按 shop_id 单店铺，规则 4）

    2026-04-26 重构：Ozon 改为按天补缺失模式
    - 在 [today-2-days+1, today-2] 范围内查 DB 已有 stat_date
    - 找出缺失天，每天调一次 days=1 的 API 单独拉
    - 每个 stat_date 装那一天的真实数字（非 N 天聚合）

    幂等保护：
    - 默认：窗口内全部天已有数据 → skip，reason='no_missing_dates'
    - 并发：Redis SETNX 锁，连点多次只跑第一次，reason='another_refresh_running'
    - 强制重拉：传 ?force=true，删窗口内所有数据 + 全部重拉

    返回：
    - 0 成功，data.synced_queries 写入行数
    - 93001 店铺未开通 Jam/Premium 订阅
    """
    result = await refresh_shop(db, tenant_id, shop, days=days, force=force)
    if result.get("code") != 0:
        return error(result["code"], result.get("msg", ""))
    return success(result["data"])
