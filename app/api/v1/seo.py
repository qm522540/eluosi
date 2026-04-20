"""SEO 优化路由（付费词反哺自然词）

前缀：/api/v1/seo
规则 1：SQL 带 tenant_id（service 层保障）
规则 4：所有接口带 {shop_id} 路径参数，全部 Depends(get_owned_shop)
"""

from typing import List, Optional
from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_tenant_id, get_owned_shop, get_current_user
from app.services.seo.service import (
    analyze_paid_to_organic, list_candidates,
    adopt_candidate, ignore_candidates,
)
from app.services.seo.title_generator import generate_title
from app.utils.response import success, error

router = APIRouter()


class BatchIgnoreBody(BaseModel):
    ids: List[int] = Field(..., min_items=1, description="候选词 id 数组")


class RefreshBody(BaseModel):
    days: int = Field(30, ge=7, le=90, description="回溯天数")
    roas_threshold: float = Field(2.0, gt=0, le=100, description="ROAS 阈值")
    min_orders: int = Field(1, ge=0, description="订单数下限")


class GenerateTitleBody(BaseModel):
    product_id: int = Field(..., gt=0, description="products.id")
    candidate_ids: List[int] = Field(..., min_items=1, max_items=30,
                                     description="要融合的候选词 id，最多 30 个")


@router.get("/shop/{shop_id}/candidates")
def list_shop_candidates(
    shop_id: int,
    source: str = Query("all", description="all / paid_self / paid_category"),
    status: str = Query("pending", description="pending / adopted / ignored / processed / all"),
    keyword: str = Query("", description="模糊关键词"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
):
    """店铺候选词清单 + 4 格汇总"""
    result = list_candidates(
        db, tenant_id, shop,
        source_filter=source, status=status, keyword=keyword,
        page=page, size=size,
    )
    if result.get("code") != 0:
        return error(result["code"], result.get("msg", ""))
    return success(result["data"])


@router.post("/shop/{shop_id}/refresh")
def refresh_shop(
    shop_id: int,
    body: RefreshBody = Body(default_factory=RefreshBody),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
):
    """手动触发引擎扫描 —— 付费词反哺 + C1-a 类目聚合，重算候选池

    返回：
    - 0 成功，data 含 analyzed_pairs / candidates / written
    """
    result = analyze_paid_to_organic(
        db, tenant_id, shop,
        days=body.days, roas_threshold=body.roas_threshold,
        min_orders=body.min_orders,
    )
    if result.get("code") != 0:
        return error(result["code"], result.get("msg", ""))
    return success(result["data"])


@router.post("/shop/{shop_id}/candidates/{candidate_id}/adopt")
def adopt(
    shop_id: int,
    candidate_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
    current_user=Depends(get_current_user),
):
    """单条候选"加入标题候选"。仅改候选池状态；三期对接 AI 标题写回商品。"""
    user_id = getattr(current_user, "id", None)
    result = adopt_candidate(db, tenant_id, shop.id, candidate_id, user_id)
    if result.get("code") != 0:
        return error(result["code"], result.get("msg", ""))
    return success(result["data"])


@router.post("/shop/{shop_id}/candidates/batch-ignore")
def batch_ignore(
    shop_id: int,
    body: BatchIgnoreBody,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
):
    """批量忽略候选（幂等，已 adopted 的跳过）"""
    result = ignore_candidates(db, tenant_id, shop.id, body.ids)
    if result.get("code") != 0:
        return error(result["code"], result.get("msg", ""))
    return success(result["data"])


@router.post("/shop/{shop_id}/generate-title")
async def generate_title_for_product(
    shop_id: int,
    body: GenerateTitleBody,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
    current_user=Depends(get_current_user),
):
    """AI 融合候选词生成商品新俄语标题（走 GLM）。

    入参 product_id + candidate_ids，service 会三重校验 (tenant/shop/product)。
    生成内容入库 seo_generated_contents 表，可后续 approve 写回商品（三期）。
    """
    user_id = getattr(current_user, "id", None)
    result = await generate_title(
        db, tenant_id, shop,
        product_id=body.product_id,
        candidate_ids=body.candidate_ids,
        user_id=user_id,
    )
    if result.get("code") != 0:
        return error(result["code"], result.get("msg", ""))
    return success(result["data"])
