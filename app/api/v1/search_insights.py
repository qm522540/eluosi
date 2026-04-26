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
    force: bool = Query(False, description="强制重拉（默认会跳过当日已有快照）"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
):
    """手动触发同步（按 shop_id 单店铺，规则 4）

    days 参数已删除（2026-04-26）：
    WB/Ozon API 只返"整段窗口聚合值"不返每天明细，days=7 vs days=30 拉到的
    数字是不同语义但写到同一行（UNIQUE KEY 命中 ON DUPLICATE 互相覆盖），
    所以固定 days=7 防止数据语义混乱。每日 beat 也用 days=7。

    幂等保护：
    - 默认：当日 stat_date 已有快照 → skip，返回 reason='snapshot_already_exists'
    - 并发：Redis SETNX 锁，连点多次只跑第一次，其余 reason='another_refresh_running'
    - 强制重拉：传 ?force=true，跳过快照预检（仍受锁约束）

    返回：
    - 0 成功，data.synced_queries 写入行数
    - 93001 店铺未开通 Jam/Premium 订阅，前端给友好提示
    """
    result = await refresh_shop(db, tenant_id, shop, days=7, force=force)
    if result.get("code") != 0:
        return error(result["code"], result.get("msg", ""))
    return success(result["data"])
