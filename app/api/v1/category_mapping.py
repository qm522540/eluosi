"""映射管理路由：本地分类 + 品类映射 + 属性映射 + 属性值映射"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_tenant_id
from app.schemas.category_mapping import (
    LocalCategoryCreate, LocalCategoryUpdate,
    CategoryMappingCreate, CategoryMappingUpdate,
    AttributeMappingCreate, AttributeMappingUpdate,
    AttributeValueMappingCreate, AttributeValueMappingUpdate,
    AISuggestCategoryRequest, AISuggestAttributesRequest, AISuggestValuesRequest,
)
from app.services.category_mapping.service import (
    list_local_categories, get_local_category_tree,
    create_local_category, update_local_category, delete_local_category,
    list_category_mappings, upsert_category_mapping,
    confirm_category_mapping, delete_category_mapping,
    list_attribute_mappings, upsert_attribute_mapping,
    confirm_attribute_mapping, delete_attribute_mapping,
    list_attribute_value_mappings, upsert_attribute_value_mapping,
    confirm_attribute_value_mapping, delete_attribute_value_mapping,
)
from app.utils.response import success, error

router = APIRouter()


# ==================== 本地分类 ====================

@router.get("/local-categories")
def local_category_list(
    parent_id: int = Query(None, description="父分类ID，0=顶级，不传=全部"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取本地分类列表"""
    result = list_local_categories(db, tenant_id, parent_id=parent_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.get("/local-categories/tree")
def local_category_tree(
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取本地分类完整树"""
    result = get_local_category_tree(db, tenant_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.post("/local-categories")
def local_category_create(
    req: LocalCategoryCreate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    result = create_local_category(db, tenant_id, req.model_dump(exclude_none=True))
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="分类创建成功")


@router.put("/local-categories/{cat_id}")
def local_category_update(
    cat_id: int,
    req: LocalCategoryUpdate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    result = update_local_category(db, tenant_id, cat_id, req.model_dump(exclude_none=True))
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.delete("/local-categories/{cat_id}")
def local_category_delete(
    cat_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    result = delete_local_category(db, tenant_id, cat_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(msg="分类已删除")


# ==================== 品类映射 ====================

@router.get("/category-mappings")
def category_mapping_list(
    local_category_id: int = Query(None),
    platform: str = Query(None),
    is_confirmed: int = Query(None),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """获取品类映射列表"""
    result = list_category_mappings(
        db, tenant_id,
        local_category_id=local_category_id,
        platform=platform, is_confirmed=is_confirmed,
    )
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.post("/category-mappings")
def category_mapping_upsert(
    req: CategoryMappingCreate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """新建或更新品类映射（按 local_category_id + platform 唯一）"""
    result = upsert_category_mapping(db, tenant_id, req.model_dump(exclude_none=True))
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="品类映射已保存")


@router.post("/category-mappings/{mapping_id}/confirm")
def category_mapping_confirm(
    mapping_id: int,
    req: CategoryMappingUpdate = None,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """人工确认品类映射（可同时修正映射值）"""
    data = req.model_dump(exclude_none=True) if req else None
    result = confirm_category_mapping(db, tenant_id, mapping_id, data)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="已确认")


@router.delete("/category-mappings/{mapping_id}")
def category_mapping_delete(
    mapping_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    result = delete_category_mapping(db, tenant_id, mapping_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(msg="映射已删除")


# ==================== 属性映射 ====================

@router.get("/attribute-mappings")
def attribute_mapping_list(
    local_category_id: int = Query(...),
    platform: str = Query(None),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    result = list_attribute_mappings(db, tenant_id, local_category_id, platform=platform)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.post("/attribute-mappings")
def attribute_mapping_upsert(
    req: AttributeMappingCreate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    result = upsert_attribute_mapping(db, tenant_id, req.model_dump(exclude_none=True))
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="属性映射已保存")


@router.post("/attribute-mappings/{mapping_id}/confirm")
def attribute_mapping_confirm(
    mapping_id: int,
    req: AttributeMappingUpdate = None,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    data = req.model_dump(exclude_none=True) if req else None
    result = confirm_attribute_mapping(db, tenant_id, mapping_id, data)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="已确认")


@router.delete("/attribute-mappings/{mapping_id}")
def attribute_mapping_delete(
    mapping_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    result = delete_attribute_mapping(db, tenant_id, mapping_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(msg="属性映射已删除")


# ==================== 属性值映射 ====================

@router.get("/attribute-value-mappings")
def attribute_value_mapping_list(
    attribute_mapping_id: int = Query(...),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    result = list_attribute_value_mappings(db, tenant_id, attribute_mapping_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.post("/attribute-value-mappings")
def attribute_value_mapping_upsert(
    req: AttributeValueMappingCreate,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    result = upsert_attribute_value_mapping(db, tenant_id, req.model_dump(exclude_none=True))
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="属性值映射已保存")


@router.post("/attribute-value-mappings/{mapping_id}/confirm")
def attribute_value_mapping_confirm(
    mapping_id: int,
    req: AttributeValueMappingUpdate = None,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    data = req.model_dump(exclude_none=True) if req else None
    result = confirm_attribute_value_mapping(db, tenant_id, mapping_id, data)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="已确认")


@router.delete("/attribute-value-mappings/{mapping_id}")
def attribute_value_mapping_delete(
    mapping_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    result = delete_attribute_value_mapping(db, tenant_id, mapping_id)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(msg="属性值映射已删除")


# ==================== AI 辅助映射推荐 ====================

@router.post("/ai-suggest/category")
async def ai_suggest_category(
    req: AISuggestCategoryRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """AI 推荐品类映射：本地分类 → 各平台分类"""
    from app.services.category_mapping.ai_suggester import suggest_category_mappings
    result = await suggest_category_mappings(
        db, tenant_id, req.local_category_id, req.shop_id, req.platforms,
    )
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="AI 推荐完成，请人工确认")


@router.post("/ai-suggest/attributes")
async def ai_suggest_attributes(
    req: AISuggestAttributesRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """AI 推荐属性映射：拉平台属性 → AI 推本地属性名"""
    from app.services.category_mapping.ai_suggester import suggest_attribute_mappings
    result = await suggest_attribute_mappings(
        db, tenant_id, req.local_category_id, req.shop_id, req.platform,
    )
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="AI 推荐完成，请人工确认")


@router.post("/ai-suggest/values")
async def ai_suggest_values(
    req: AISuggestValuesRequest,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """AI 推荐属性值映射：本地枚举值 → 平台字典枚举值

    前置：属性映射 value_type=enum + 对应品类映射存在
    """
    from app.services.category_mapping.ai_suggester import suggest_attribute_value_mappings
    result = await suggest_attribute_value_mappings(
        db, tenant_id, req.attribute_mapping_id, req.local_values, req.shop_id,
    )
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="AI 推荐完成，请人工确认")
