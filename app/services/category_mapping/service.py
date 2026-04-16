"""映射管理业务逻辑：本地分类 + 品类映射 + 属性映射 + 属性值映射"""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session

from app.models.category import (
    LocalCategory, CategoryPlatformMapping,
    AttributeMapping, AttributeValueMapping,
)
from app.utils.errors import ErrorCode
from app.utils.logger import logger


# ==================== 本地分类 ====================

def list_local_categories(db: Session, tenant_id: int, parent_id: Optional[int] = None) -> dict:
    """获取本地分类列表（树形或扁平）"""
    try:
        query = db.query(LocalCategory).filter(
            LocalCategory.tenant_id == tenant_id,
            LocalCategory.status == "active",
        )
        if parent_id is not None:
            if parent_id == 0:
                query = query.filter(LocalCategory.parent_id.is_(None))
            else:
                query = query.filter(LocalCategory.parent_id == parent_id)
        items = query.order_by(LocalCategory.level, LocalCategory.sort_order).all()
        return {"code": 0, "data": {"items": [_local_cat_to_dict(c) for c in items]}}
    except Exception as e:
        logger.error(f"获取本地分类失败 tenant_id={tenant_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取本地分类失败"}


def get_local_category_tree(db: Session, tenant_id: int) -> dict:
    """返回完整的本地分类树"""
    try:
        items = db.query(LocalCategory).filter(
            LocalCategory.tenant_id == tenant_id,
            LocalCategory.status == "active",
        ).order_by(LocalCategory.level, LocalCategory.sort_order).all()
        # 组装树
        node_map = {}
        for c in items:
            node = _local_cat_to_dict(c)
            node["children"] = []
            node_map[c.id] = node
        roots = []
        for c in items:
            node = node_map[c.id]
            if c.parent_id and c.parent_id in node_map:
                node_map[c.parent_id]["children"].append(node)
            else:
                roots.append(node)
        return {"code": 0, "data": {"tree": roots}}
    except Exception as e:
        logger.error(f"获取本地分类树失败 tenant_id={tenant_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取本地分类树失败"}


def create_local_category(db: Session, tenant_id: int, data: dict) -> dict:
    try:
        parent_id = data.get("parent_id")
        level = 1
        if parent_id:
            parent = db.query(LocalCategory).filter(
                LocalCategory.id == parent_id,
                LocalCategory.tenant_id == tenant_id,
            ).first()
            if not parent:
                return {"code": ErrorCode.PARAM_ERROR, "msg": "父分类不存在"}
            level = parent.level + 1
            if level > 3:
                return {"code": ErrorCode.PARAM_ERROR, "msg": "分类最多3级"}
        cat = LocalCategory(tenant_id=tenant_id, level=level, **data)
        db.add(cat)
        db.commit()
        db.refresh(cat)
        return {"code": 0, "data": _local_cat_to_dict(cat)}
    except Exception as e:
        db.rollback()
        logger.error(f"创建本地分类失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "创建本地分类失败"}


def update_local_category(db: Session, tenant_id: int, cat_id: int, data: dict) -> dict:
    try:
        cat = db.query(LocalCategory).filter(
            LocalCategory.id == cat_id,
            LocalCategory.tenant_id == tenant_id,
        ).first()
        if not cat:
            return {"code": ErrorCode.PARAM_ERROR, "msg": "分类不存在"}
        for k, v in data.items():
            if v is not None:
                setattr(cat, k, v)
        db.commit()
        db.refresh(cat)
        return {"code": 0, "data": _local_cat_to_dict(cat)}
    except Exception as e:
        db.rollback()
        logger.error(f"更新本地分类失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "更新本地分类失败"}


def delete_local_category(db: Session, tenant_id: int, cat_id: int) -> dict:
    try:
        cat = db.query(LocalCategory).filter(
            LocalCategory.id == cat_id,
            LocalCategory.tenant_id == tenant_id,
        ).first()
        if not cat:
            return {"code": ErrorCode.PARAM_ERROR, "msg": "分类不存在"}
        # 检查是否有子分类
        has_child = db.query(LocalCategory).filter(
            LocalCategory.parent_id == cat_id,
            LocalCategory.tenant_id == tenant_id,
            LocalCategory.status == "active",
        ).first()
        if has_child:
            return {"code": ErrorCode.PARAM_ERROR, "msg": "请先删除子分类"}
        cat.status = "inactive"
        # 同时把相关映射删除
        db.query(CategoryPlatformMapping).filter(
            CategoryPlatformMapping.tenant_id == tenant_id,
            CategoryPlatformMapping.local_category_id == cat_id,
        ).delete()
        db.commit()
        return {"code": 0, "data": None}
    except Exception as e:
        db.rollback()
        logger.error(f"删除本地分类失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "删除本地分类失败"}


# ==================== 品类映射 ====================

def list_category_mappings(
    db: Session, tenant_id: int,
    local_category_id: Optional[int] = None,
    platform: Optional[str] = None,
    is_confirmed: Optional[int] = None,
) -> dict:
    try:
        query = db.query(CategoryPlatformMapping).filter(
            CategoryPlatformMapping.tenant_id == tenant_id
        )
        if local_category_id is not None:
            query = query.filter(CategoryPlatformMapping.local_category_id == local_category_id)
        if platform:
            query = query.filter(CategoryPlatformMapping.platform == platform)
        if is_confirmed is not None:
            query = query.filter(CategoryPlatformMapping.is_confirmed == is_confirmed)
        items = query.all()
        return {"code": 0, "data": {"items": [_cat_mapping_to_dict(m) for m in items]}}
    except Exception as e:
        logger.error(f"获取品类映射失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取品类映射失败"}


def upsert_category_mapping(db: Session, tenant_id: int, data: dict) -> dict:
    """新建或更新品类映射（按 tenant_id + local_category_id + platform 唯一）"""
    try:
        existing = db.query(CategoryPlatformMapping).filter(
            CategoryPlatformMapping.tenant_id == tenant_id,
            CategoryPlatformMapping.local_category_id == data["local_category_id"],
            CategoryPlatformMapping.platform == data["platform"],
        ).first()
        if existing:
            for k, v in data.items():
                if v is not None and k not in ("local_category_id", "platform"):
                    setattr(existing, k, v)
            db.commit()
            db.refresh(existing)
            return {"code": 0, "data": _cat_mapping_to_dict(existing)}
        mapping = CategoryPlatformMapping(tenant_id=tenant_id, **data)
        db.add(mapping)
        db.commit()
        db.refresh(mapping)
        return {"code": 0, "data": _cat_mapping_to_dict(mapping)}
    except Exception as e:
        db.rollback()
        logger.error(f"保存品类映射失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "保存品类映射失败"}


def confirm_category_mapping(db: Session, tenant_id: int, mapping_id: int, data: dict = None) -> dict:
    """人工确认品类映射（可同时修改映射值）"""
    try:
        mapping = db.query(CategoryPlatformMapping).filter(
            CategoryPlatformMapping.id == mapping_id,
            CategoryPlatformMapping.tenant_id == tenant_id,
        ).first()
        if not mapping:
            return {"code": ErrorCode.PARAM_ERROR, "msg": "映射不存在"}
        if data:
            for k, v in data.items():
                if v is not None and k != "is_confirmed":
                    setattr(mapping, k, v)
        mapping.is_confirmed = 1
        mapping.confirmed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(mapping)
        return {"code": 0, "data": _cat_mapping_to_dict(mapping)}
    except Exception as e:
        db.rollback()
        logger.error(f"确认品类映射失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "确认品类映射失败"}


def delete_category_mapping(db: Session, tenant_id: int, mapping_id: int) -> dict:
    try:
        mapping = db.query(CategoryPlatformMapping).filter(
            CategoryPlatformMapping.id == mapping_id,
            CategoryPlatformMapping.tenant_id == tenant_id,
        ).first()
        if not mapping:
            return {"code": ErrorCode.PARAM_ERROR, "msg": "映射不存在"}
        db.delete(mapping)
        db.commit()
        return {"code": 0, "data": None}
    except Exception as e:
        db.rollback()
        logger.error(f"删除品类映射失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "删除品类映射失败"}


# ==================== 属性映射 ====================

def list_attribute_mappings(
    db: Session, tenant_id: int,
    local_category_id: int, platform: Optional[str] = None,
) -> dict:
    try:
        query = db.query(AttributeMapping).filter(
            AttributeMapping.tenant_id == tenant_id,
            AttributeMapping.local_category_id == local_category_id,
        )
        if platform:
            query = query.filter(AttributeMapping.platform == platform)
        items = query.all()
        return {"code": 0, "data": {"items": [_attr_mapping_to_dict(m) for m in items]}}
    except Exception as e:
        logger.error(f"获取属性映射失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取属性映射失败"}


def upsert_attribute_mapping(db: Session, tenant_id: int, data: dict) -> dict:
    try:
        existing = db.query(AttributeMapping).filter(
            AttributeMapping.tenant_id == tenant_id,
            AttributeMapping.local_category_id == data["local_category_id"],
            AttributeMapping.local_attr_name == data["local_attr_name"],
            AttributeMapping.platform == data["platform"],
        ).first()
        if existing:
            for k, v in data.items():
                if v is not None and k not in ("local_category_id", "local_attr_name", "platform"):
                    setattr(existing, k, v)
            db.commit()
            db.refresh(existing)
            return {"code": 0, "data": _attr_mapping_to_dict(existing)}
        mapping = AttributeMapping(tenant_id=tenant_id, **data)
        db.add(mapping)
        db.commit()
        db.refresh(mapping)
        return {"code": 0, "data": _attr_mapping_to_dict(mapping)}
    except Exception as e:
        db.rollback()
        logger.error(f"保存属性映射失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "保存属性映射失败"}


def confirm_attribute_mapping(db: Session, tenant_id: int, mapping_id: int, data: dict = None) -> dict:
    try:
        mapping = db.query(AttributeMapping).filter(
            AttributeMapping.id == mapping_id,
            AttributeMapping.tenant_id == tenant_id,
        ).first()
        if not mapping:
            return {"code": ErrorCode.PARAM_ERROR, "msg": "映射不存在"}
        if data:
            for k, v in data.items():
                if v is not None and k != "is_confirmed":
                    setattr(mapping, k, v)
        mapping.is_confirmed = 1
        mapping.confirmed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(mapping)
        return {"code": 0, "data": _attr_mapping_to_dict(mapping)}
    except Exception as e:
        db.rollback()
        logger.error(f"确认属性映射失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "确认属性映射失败"}


def delete_attribute_mapping(db: Session, tenant_id: int, mapping_id: int) -> dict:
    try:
        mapping = db.query(AttributeMapping).filter(
            AttributeMapping.id == mapping_id,
            AttributeMapping.tenant_id == tenant_id,
        ).first()
        if not mapping:
            return {"code": ErrorCode.PARAM_ERROR, "msg": "映射不存在"}
        # 连带删除属性值映射
        db.query(AttributeValueMapping).filter(
            AttributeValueMapping.tenant_id == tenant_id,
            AttributeValueMapping.attribute_mapping_id == mapping_id,
        ).delete()
        db.delete(mapping)
        db.commit()
        return {"code": 0, "data": None}
    except Exception as e:
        db.rollback()
        logger.error(f"删除属性映射失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "删除属性映射失败"}


# ==================== 属性值映射 ====================

def list_attribute_value_mappings(
    db: Session, tenant_id: int, attribute_mapping_id: int,
) -> dict:
    try:
        items = db.query(AttributeValueMapping).filter(
            AttributeValueMapping.tenant_id == tenant_id,
            AttributeValueMapping.attribute_mapping_id == attribute_mapping_id,
        ).all()
        return {"code": 0, "data": {"items": [_attr_value_to_dict(m) for m in items]}}
    except Exception as e:
        logger.error(f"获取属性值映射失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取属性值映射失败"}


def upsert_attribute_value_mapping(db: Session, tenant_id: int, data: dict) -> dict:
    try:
        existing = db.query(AttributeValueMapping).filter(
            AttributeValueMapping.tenant_id == tenant_id,
            AttributeValueMapping.attribute_mapping_id == data["attribute_mapping_id"],
            AttributeValueMapping.local_value == data["local_value"],
        ).first()
        if existing:
            for k, v in data.items():
                if v is not None and k not in ("attribute_mapping_id", "local_value"):
                    setattr(existing, k, v)
            db.commit()
            db.refresh(existing)
            return {"code": 0, "data": _attr_value_to_dict(existing)}
        mapping = AttributeValueMapping(tenant_id=tenant_id, **data)
        db.add(mapping)
        db.commit()
        db.refresh(mapping)
        return {"code": 0, "data": _attr_value_to_dict(mapping)}
    except Exception as e:
        db.rollback()
        logger.error(f"保存属性值映射失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "保存属性值映射失败"}


def confirm_attribute_value_mapping(db: Session, tenant_id: int, mapping_id: int, data: dict = None) -> dict:
    try:
        mapping = db.query(AttributeValueMapping).filter(
            AttributeValueMapping.id == mapping_id,
            AttributeValueMapping.tenant_id == tenant_id,
        ).first()
        if not mapping:
            return {"code": ErrorCode.PARAM_ERROR, "msg": "映射不存在"}
        if data:
            for k, v in data.items():
                if v is not None and k != "is_confirmed":
                    setattr(mapping, k, v)
        mapping.is_confirmed = 1
        mapping.confirmed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(mapping)
        return {"code": 0, "data": _attr_value_to_dict(mapping)}
    except Exception as e:
        db.rollback()
        logger.error(f"确认属性值映射失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "确认属性值映射失败"}


def delete_attribute_value_mapping(db: Session, tenant_id: int, mapping_id: int) -> dict:
    try:
        mapping = db.query(AttributeValueMapping).filter(
            AttributeValueMapping.id == mapping_id,
            AttributeValueMapping.tenant_id == tenant_id,
        ).first()
        if not mapping:
            return {"code": ErrorCode.PARAM_ERROR, "msg": "映射不存在"}
        db.delete(mapping)
        db.commit()
        return {"code": 0, "data": None}
    except Exception as e:
        db.rollback()
        logger.error(f"删除属性值映射失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "删除属性值映射失败"}


# ==================== 辅助函数 ====================

def _local_cat_to_dict(c: LocalCategory) -> dict:
    return {
        "id": c.id,
        "parent_id": c.parent_id,
        "name": c.name,
        "name_ru": c.name_ru,
        "level": c.level,
        "sort_order": c.sort_order,
        "status": c.status,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def _cat_mapping_to_dict(m: CategoryPlatformMapping) -> dict:
    return {
        "id": m.id,
        "local_category_id": m.local_category_id,
        "platform": m.platform,
        "platform_category_id": m.platform_category_id,
        "platform_category_name": m.platform_category_name,
        "platform_parent_path": m.platform_parent_path,
        "ai_suggested": m.ai_suggested,
        "ai_confidence": m.ai_confidence,
        "is_confirmed": m.is_confirmed,
        "confirmed_at": m.confirmed_at.isoformat() if m.confirmed_at else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def _attr_mapping_to_dict(m: AttributeMapping) -> dict:
    return {
        "id": m.id,
        "local_category_id": m.local_category_id,
        "local_attr_name": m.local_attr_name,
        "local_attr_name_ru": m.local_attr_name_ru,
        "platform": m.platform,
        "platform_attr_id": m.platform_attr_id,
        "platform_attr_name": m.platform_attr_name,
        "is_required": m.is_required,
        "value_type": m.value_type,
        "platform_dict_id": m.platform_dict_id,
        "ai_suggested": m.ai_suggested,
        "ai_confidence": m.ai_confidence,
        "is_confirmed": m.is_confirmed,
        "confirmed_at": m.confirmed_at.isoformat() if m.confirmed_at else None,
    }


def _attr_value_to_dict(m: AttributeValueMapping) -> dict:
    return {
        "id": m.id,
        "attribute_mapping_id": m.attribute_mapping_id,
        "local_value": m.local_value,
        "local_value_ru": m.local_value_ru,
        "platform_value": m.platform_value,
        "platform_value_id": m.platform_value_id,
        "ai_suggested": m.ai_suggested,
        "ai_confidence": m.ai_confidence,
        "is_confirmed": m.is_confirmed,
        "confirmed_at": m.confirmed_at.isoformat() if m.confirmed_at else None,
    }
