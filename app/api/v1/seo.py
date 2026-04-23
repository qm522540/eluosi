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
    list_champion_keywords,
)
from app.services.seo.title_generator import generate_title
from app.services.seo.health_service import compute_shop_health
from app.services.seo.generated_history import list_generated_titles, mark_title_applied
from app.services.seo.keyword_tracking_service import compute_keyword_tracking, list_query_top_skus
from app.services.seo.roi_report_service import compute_roi_report
from app.services.seo.keyword_rollup_service import (
    compute_keyword_rollup, list_rollup_products,
    compute_candidates_rollup, list_candidates_rollup_products,
    list_category_evidence_top_products, list_cross_shop_top_products,
)
from app.utils.response import success, error

router = APIRouter()


class BatchIgnoreBody(BaseModel):
    ids: List[int] = Field(..., min_length=1, description="候选词 id 数组")


class RefreshBody(BaseModel):
    days: int = Field(30, ge=7, le=90, description="回溯天数")
    roas_threshold: float = Field(2.0, gt=0, le=100, description="ROAS 阈值")
    min_orders: int = Field(1, ge=0, description="订单数下限")


class GenerateTitleBody(BaseModel):
    product_id: int = Field(..., gt=0, description="products.id")
    candidate_ids: List[int] = Field(..., min_length=1, max_length=30,
                                     description="要融合的候选词 id，最多 30 个")


@router.get("/shop/{shop_id}/champion-keywords")
def list_shop_champion_keywords(
    shop_id: int,
    limit: int = Query(10, ge=1, le=30, description="返回 Top N"),
    min_products: int = Query(2, ge=2, le=50, description="至少覆盖 N 个商品才算爆款词"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
):
    """跨商品爆款词：带订单 + 多个商品标题/属性都未覆盖。

    业务场景：用户一眼看到"该批量改哪个词，全店多少商品能受益"。
    """
    result = list_champion_keywords(
        db, tenant_id, shop,
        limit=limit, min_products=min_products,
    )
    if result.get("code") != 0:
        return error(result["code"], result.get("msg", ""))
    return success(result["data"])


@router.get("/shop/{shop_id}/candidates")
def list_shop_candidates(
    shop_id: int,
    source: str = Query("all", description="all / paid_self / paid_category / organic_self / organic_category / with_orders"),
    status: str = Query("pending", description="pending / adopted / ignored / processed / all"),
    keyword: str = Query("", description="模糊关键词"),
    product_id: Optional[int] = Query(None, description="过滤到单个商品（Health 闭环用）"),
    hide_covered: bool = Query(False, description="True 时隐藏已在标题里的词（改无意义）"),
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
        product_id=product_id,
        hide_covered=hide_covered,
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


@router.get("/shop/{shop_id}/health")
def shop_health(
    shop_id: int,
    score_range: str = Query("all", description="all / poor / fair / good / data_insufficient"),
    sort: str = Query("score_asc", description="score_asc / score_desc / gaps_desc"),
    keyword: str = Query("", description="商品名模糊搜索"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
):
    """店铺 SEO 健康分诊断 + Top 缺词。"""
    result = compute_shop_health(
        db, tenant_id, shop,
        score_range=score_range, sort=sort, keyword=keyword,
        page=page, size=size,
    )
    if result.get("code") != 0:
        return error(result["code"], result.get("msg", ""))
    return success(result["data"])


@router.get("/shop/{shop_id}/generated-titles")
def list_generated(
    shop_id: int,
    keyword: str = Query("", description="原标题或新标题模糊搜"),
    approval_status: str = Query("all", description="all / pending / approved / applied / rejected"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
):
    """店铺 AI 生成标题历史（分页），只取 content_type='title'。"""
    result = list_generated_titles(
        db, tenant_id, shop,
        keyword=keyword, approval_status=approval_status,
        page=page, size=size,
    )
    if result.get("code") != 0:
        return error(result["code"], result.get("msg", ""))
    return success(result["data"])


@router.post("/shop/{shop_id}/generated-titles/{generated_id}/apply")
def apply_generated(
    shop_id: int,
    generated_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
    current_user=Depends(get_current_user),
):
    """用户手动确认"已复制并改到商品"，标 applied_at + approved_by。"""
    user_id = getattr(current_user, "id", None)
    result = mark_title_applied(db, tenant_id, shop, generated_id, user_id)
    if result.get("code") != 0:
        return error(result["code"], result.get("msg", ""))
    return success(result["data"])


@router.get("/shop/{shop_id}/roi-report")
def shop_roi_report(
    shop_id: int,
    window_days: int = Query(14, ge=3, le=60, description="Before/After 窗口天数"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
):
    """改标题 Before/After ROI 对比。

    对所有 approval_status='applied' 的记录，以 applied_at 为切割点，
    从 product_search_queries 聚合前后 window_days 天的曝光/订单/营收。

    status='observing' 表示 applied_at 距今不足 window_days，观察期未满。
    """
    result = compute_roi_report(
        db, tenant_id, shop,
        window_days=window_days,
    )
    if result.get("code") != 0:
        return error(result["code"], result.get("msg", ""))
    return success(result["data"])


@router.get("/shop/{shop_id}/keyword-tracking")
def shop_keyword_tracking(
    shop_id: int,
    date_range: int = Query(7, ge=1, le=30, description="本期天数（上期同长度）"),
    sort: str = Query("impressions_desc", description="impressions_desc / orders_desc / drop_desc / new_desc"),
    keyword: str = Query("", description="query_text 模糊搜索"),
    min_impressions: int = Query(0, ge=0, description="过滤低曝光噪声"),
    alert_only: bool = Query(False, description="仅看下滑预警词"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
):
    """店铺核心词表现追踪 — 本期 vs 上期 环比 + 下滑预警。

    数据未就绪（WB 未订阅 Jam / Ozon 未订阅 Premium）时返 data_status='not_ready'
    + 平台专属引导文案，前端据此渲染空态。
    """
    result = compute_keyword_tracking(
        db, tenant_id, shop,
        date_range=date_range, sort=sort,
        keyword=keyword, min_impressions=min_impressions,
        alert_only=alert_only, page=page, size=size,
    )
    if result.get("code") != 0:
        return error(result["code"], result.get("msg", ""))
    return success(result["data"])


@router.get("/shop/{shop_id}/keyword-tracking/skus")
def shop_keyword_tracking_skus(
    shop_id: int,
    query_text: str = Query(..., min_length=1, description="要下钻的核心词"),
    date_range: int = Query(7, ge=1, le=30),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
):
    """单核心词下钻：哪些商品靠这个词带曝光/订单。"""
    result = list_query_top_skus(
        db, tenant_id, shop,
        query_text=query_text, date_range=date_range, limit=limit,
    )
    if result.get("code") != 0:
        return error(result["code"], result.get("msg", ""))
    return success(result["data"])


@router.get("/shop/{shop_id}/keyword-rollup")
def shop_keyword_rollup(
    shop_id: int,
    days: int = Query(30, ge=7, le=90, description="回溯窗口天数"),
    sort: str = Query("revenue_desc", description="revenue_desc / orders_desc / impressions_desc / cart_desc"),
    keyword: str = Query("", description="关键词模糊筛选"),
    min_orders: int = Query(0, ge=0, description="订单数下限（过滤零单噪声）"),
    limit: int = Query(100, ge=10, le=500, description="最多返回 N 条"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
):
    """店级关键词聚合：每行 = 关键词，跨商品汇总（自然搜索 organic scope）

    与 /candidates 不同，此视图按 query_text 一维聚合；
    同一个词跨多商品的总贡献一目了然，排名靠前的是店铺摇钱树。
    """
    result = compute_keyword_rollup(
        db, tenant_id, shop,
        days=days, sort=sort, keyword=keyword,
        min_orders=min_orders, limit=limit,
    )
    if result.get("code") != 0:
        return error(result["code"], result.get("msg", ""))
    return success(result["data"])


@router.get("/shop/{shop_id}/keyword-rollup/products")
def shop_keyword_rollup_products(
    shop_id: int,
    keyword: str = Query(..., min_length=1, description="要下钻的关键词"),
    days: int = Query(30, ge=7, le=90),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
):
    """单关键词下钻：看该词在各商品的贡献（缩略图 + 标题 + 曝光/加购/订单/收入）"""
    result = list_rollup_products(
        db, tenant_id, shop,
        keyword=keyword, days=days, limit=limit,
    )
    if result.get("code") != 0:
        return error(result["code"], result.get("msg", ""))
    return success(result["data"])


@router.get("/shop/{shop_id}/candidates-rollup")
def shop_candidates_rollup(
    shop_id: int,
    source: str = Query("all", description="all / paid_self / paid_category / organic_self / organic_category / with_orders"),
    status: str = Query("pending", description="pending / adopted / ignored"),
    keyword: str = Query("", description="关键词模糊筛"),
    hide_covered: bool = Query(True, description="隐藏已在标题/属性的候选"),
    sort: str = Query("score_desc", description="score_desc / orders_desc / impr_desc / products_desc"),
    limit: int = Query(200, ge=10, le=500),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
):
    """按商品看 Tab 的关键词聚合主视图（走 seo_keyword_candidates，含 paid/organic/类目扩散）

    与 /keyword-rollup（走 product_search_queries）口径不同：
    candidates-rollup 含引擎加工后的候选池+反哺评分，是"决策视图"。
    """
    result = compute_candidates_rollup(
        db, tenant_id, shop,
        source=source, status=status, keyword=keyword,
        hide_covered=hide_covered, sort=sort, limit=limit,
    )
    if result.get("code") != 0:
        return error(result["code"], result.get("msg", ""))
    return success(result["data"])


@router.get("/shop/{shop_id}/candidates-rollup/products")
def shop_candidates_rollup_products(
    shop_id: int,
    keyword: str = Query(..., min_length=1),
    status: str = Query("pending"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
):
    """单关键词下钻：展开该词下所有候选商品（含 self 真实数据 + category 推断，自带 has_self 标记）

    每条 category-only（0 曝光·系统推荐加词）行附带 category_evidence 字段，
    说明"类目里 N 款真实搜中 · X 订单"作为推荐理由。
    """
    result = list_candidates_rollup_products(
        db, tenant_id, shop,
        keyword=keyword, status=status, limit=limit,
    )
    if result.get("code") != 0:
        return error(result["code"], result.get("msg", ""))
    return success(result["data"])


@router.get("/shop/{shop_id}/candidates-rollup/category-evidence")
def shop_candidates_rollup_category_evidence(
    shop_id: int,
    keyword: str = Query(..., min_length=1, description="关键词"),
    category_id: int = Query(..., description="商品本地类目 ID"),
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
):
    """点推荐理由 Tag 弹出 Modal 展示：该类目下对该关键词真实搜中的 Top N 商品详情"""
    result = list_category_evidence_top_products(
        db, tenant_id, shop,
        keyword=keyword, category_id=category_id, limit=limit,
    )
    if result.get("code") != 0:
        return error(result["code"], result.get("msg", ""))
    return success(result["data"])


@router.get("/shop/{shop_id}/candidates-rollup/cross-shop-evidence")
def shop_candidates_rollup_cross_shop_evidence(
    shop_id: int,
    keyword: str = Query(..., min_length=1, description="关键词"),
    product_sku: str = Query(..., min_length=1, description="本地编码 products.sku"),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    shop=Depends(get_owned_shop),
):
    """点「跨店同款」Tag 弹 Modal：该 products.sku 在当前店铺外其他 shop 的真实搜中明细"""
    result = list_cross_shop_top_products(
        db, tenant_id, shop,
        keyword=keyword, product_sku=product_sku, limit=limit,
    )
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
