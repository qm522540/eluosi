"""店铺克隆模块 Pydantic schemas

按 docs/api/store_clone.md §5 接口规范。

入参 schemas 用于路由层校验请求体；
响应不强制走 schemas（service 层返回 dict + ErrorCode 风格，与现有 ai_pricing/seo 一致），
但部分复杂响应（如 pending 列表的 source/proposed 嵌套）提供类型提示供 IDE / 文档参考。

关联文档: docs/api/store_clone.md
关联模型: app/models/clone.py
关联迁移: 061 / 062
"""

from typing import Optional, List, Literal
from decimal import Decimal
from pydantic import BaseModel, Field, model_validator


# ==================== §5.1 任务管理 ====================

class CloneTaskCreate(BaseModel):
    """POST /tasks 请求体"""
    target_shop_id: int = Field(..., gt=0, description="A 店（落地店）shop_id")
    source_shop_id: int = Field(..., gt=0, description="B 店（被跟踪店）shop_id；Phase 1 必填")

    title_mode: Literal["original", "ai_rewrite"] = "original"
    desc_mode: Literal["original", "ai_rewrite"] = "original"

    price_mode: Literal["same", "adjust_pct"] = "same"
    price_adjust_pct: Optional[Decimal] = Field(
        None, ge=-50, le=200,
        description="正数=涨，负数=跌；price_mode=adjust_pct 时必填",
    )

    default_stock: int = Field(999, ge=0, le=999999)
    follow_price_change: bool = False

    category_strategy: Literal["same_platform", "use_local_map", "reject_if_missing"] = "use_local_map"

    is_active: bool = False

    @model_validator(mode="after")
    def _check_constraints(self):
        if self.target_shop_id == self.source_shop_id:
            raise ValueError("target_shop_id 不能等于 source_shop_id")
        if self.price_mode == "adjust_pct" and self.price_adjust_pct is None:
            raise ValueError("price_mode=adjust_pct 时 price_adjust_pct 必填")
        return self


class CloneTaskUpdate(BaseModel):
    """PUT /tasks/{task_id} 请求体；所有字段可选，仅更新传入的"""
    title_mode: Optional[Literal["original", "ai_rewrite"]] = None
    desc_mode: Optional[Literal["original", "ai_rewrite"]] = None

    price_mode: Optional[Literal["same", "adjust_pct"]] = None
    price_adjust_pct: Optional[Decimal] = Field(None, ge=-50, le=200)

    default_stock: Optional[int] = Field(None, ge=0, le=999999)
    follow_price_change: Optional[bool] = None

    category_strategy: Optional[Literal["same_platform", "use_local_map", "reject_if_missing"]] = None

    @model_validator(mode="after")
    def _check_pct(self):
        if self.price_mode == "adjust_pct" and self.price_adjust_pct is None:
            raise ValueError("price_mode=adjust_pct 时 price_adjust_pct 必填")
        return self


class ScanNowResult(BaseModel):
    """POST /tasks/{task_id}/scan-now 响应 data"""
    found: int
    new: int
    skip_published: int
    skip_rejected: int
    skip_category_missing: int
    ai_rewrite_total: int = 0
    ai_rewrite_failed: int = 0
    duration_ms: int
    log_id: int


# ==================== §5.2 待审核商品 ====================

class RejectRequest(BaseModel):
    """POST /pending/{id}/reject 请求体"""
    reject_reason: Optional[str] = Field(None, max_length=200)


class PendingPayloadUpdate(BaseModel):
    """PUT /pending/{id} 请求体；审核前修改 proposed_payload

    proposed_payload 整体结构由 service 层校验，schema 只做透传 +
    顶层 key 白名单（防止用户塞乱七八糟字段污染 JSON）。
    """
    proposed_payload: dict = Field(
        ...,
        description="JSON: {title_ru?, description_ru?, price_rub?, stock?, "
                    "images_oss?, platform_category_id?, attributes?}；"
                    "仅传需要修改的字段，service 层 merge 到现有 proposed_payload",
    )


class BatchActionRequest(BaseModel):
    """POST /pending/approve-batch / reject-batch 请求体"""
    ids: List[int] = Field(..., min_length=1, max_length=100,
                           description="批量操作的 pending_id 列表，单次最多 100 个")
    reject_reason: Optional[str] = Field(None, max_length=200,
                                         description="reject-batch 时可选；approve-batch 忽略")


# ==================== §5.4 配置辅助 ====================

class AvailableShop(BaseModel):
    """GET /available-shops 响应 items[] 元素"""
    id: int
    name: str
    platform: Literal["wb", "ozon", "yandex"]
    has_seller_token: bool
    is_active: bool


class CategoryCoverageItem(BaseModel):
    """GET /category-coverage/{task_id} 响应 missing_categories[] 元素"""
    platform_category_id: str
    platform_category_name: Optional[str] = None
    sku_count: int


# ==================== 响应辅助类型（非强制） ====================
# service 层返回 dict + ErrorCode 风格（与 ai_pricing / seo 一致），
# 下面类只用于 IDE / 文档参考嵌套结构，不走 response_model 校验。

class PendingSourceSnapshot(BaseModel):
    """clone_pending_products.source_snapshot JSON 结构"""
    platform: Literal["wb", "ozon", "yandex"]
    sku_id: str
    title_ru: str
    description_ru: Optional[str] = None
    price_rub: Decimal
    stock: int
    images: List[str] = Field(default_factory=list)
    platform_category_id: Optional[str] = None
    platform_category_name: Optional[str] = None
    attributes: List[dict] = Field(default_factory=list)


class PendingProposedPayload(BaseModel):
    """clone_pending_products.proposed_payload JSON 结构

    `_ai_rewrite_failed_*` 字段（带下划线前缀）是 fallback 标记位，
    前端见到角标提示用户手动改或重触发 AI（详见 store_clone.md §4.1 末尾约定）。
    """
    title_ru: str
    description_ru: Optional[str] = None
    price_rub: Decimal
    stock: int
    images_oss: List[str] = Field(default_factory=list)
    platform_category_id: str
    platform_category_name: Optional[str] = None
    attributes: List[dict] = Field(default_factory=list)
    # AI 改写 fallback 标记位（可选）
    ai_rewrite_failed_title: Optional[bool] = Field(None, alias="_ai_rewrite_failed_title")
    ai_rewrite_failed_desc: Optional[bool] = Field(None, alias="_ai_rewrite_failed_desc")
    ai_rewrite_error: Optional[str] = Field(None, alias="_ai_rewrite_error")

    model_config = {"populate_by_name": True}
