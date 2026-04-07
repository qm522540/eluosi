"""店铺业务逻辑"""

from sqlalchemy.orm import Session

from app.models.shop import Shop
from app.models.tenant import Tenant
from app.services.platform.base import PlatformClientFactory
from app.utils.errors import ErrorCode
from app.utils.logger import logger


def list_shops(db: Session, tenant_id: int, platform: str = None, status: str = None,
               page: int = 1, page_size: int = 20) -> dict:
    """获取店铺列表"""
    try:
        query = db.query(Shop).filter(
            Shop.tenant_id == tenant_id,
            Shop.status != "deleted"
        )
        if platform:
            query = query.filter(Shop.platform == platform)
        if status:
            query = query.filter(Shop.status == status)

        total = query.count()
        shops = query.order_by(Shop.created_at.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()

        items = [_shop_to_dict(s) for s in shops]
        return {
            "code": ErrorCode.SUCCESS,
            "data": {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": (total + page_size - 1) // page_size,
            },
        }
    except Exception as e:
        logger.error(f"获取店铺列表失败 tenant_id={tenant_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取店铺列表失败"}


def create_shop(db: Session, tenant_id: int, data: dict) -> dict:
    """创建店铺"""
    try:
        # 检查店铺数量限制
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            return {"code": ErrorCode.NOT_FOUND, "msg": "租户不存在"}

        current_count = db.query(Shop).filter(
            Shop.tenant_id == tenant_id,
            Shop.status != "deleted"
        ).count()
        if current_count >= tenant.max_shops:
            return {"code": ErrorCode.SHOP_LIMIT_EXCEEDED, "msg": f"店铺数量已达上限({tenant.max_shops})"}

        shop = Shop(tenant_id=tenant_id, **data)
        db.add(shop)
        db.commit()
        db.refresh(shop)

        logger.info(f"店铺创建成功: shop_id={shop.id} platform={shop.platform} tenant_id={tenant_id}")
        return {"code": ErrorCode.SUCCESS, "data": _shop_to_dict(shop)}
    except Exception as e:
        db.rollback()
        logger.error(f"创建店铺失败 tenant_id={tenant_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "创建店铺失败"}


def get_shop(db: Session, shop_id: int, tenant_id: int) -> dict:
    """获取店铺详情"""
    try:
        shop = db.query(Shop).filter(
            Shop.id == shop_id,
            Shop.tenant_id == tenant_id,
            Shop.status != "deleted"
        ).first()

        if not shop:
            return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在"}

        detail = _shop_to_dict(shop)
        detail["has_api_key"] = bool(shop.api_key)
        detail["has_api_secret"] = bool(shop.api_secret)
        detail["has_client_id"] = bool(shop.client_id)
        detail["has_oauth_token"] = bool(shop.oauth_token)

        return {"code": ErrorCode.SUCCESS, "data": detail}
    except Exception as e:
        logger.error(f"获取店铺详情失败 shop_id={shop_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取店铺详情失败"}


def update_shop(db: Session, shop_id: int, tenant_id: int, data: dict) -> dict:
    """更新店铺"""
    try:
        shop = db.query(Shop).filter(
            Shop.id == shop_id,
            Shop.tenant_id == tenant_id,
            Shop.status != "deleted"
        ).first()

        if not shop:
            return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在"}

        for key, value in data.items():
            if value is not None:
                setattr(shop, key, value)

        db.commit()
        db.refresh(shop)

        logger.info(f"店铺更新成功: shop_id={shop.id}")
        return {"code": ErrorCode.SUCCESS, "data": _shop_to_dict(shop)}
    except Exception as e:
        db.rollback()
        logger.error(f"更新店铺失败 shop_id={shop_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "更新店铺失败"}


def delete_shop(db: Session, shop_id: int, tenant_id: int) -> dict:
    """删除店铺（软删除）"""
    try:
        shop = db.query(Shop).filter(
            Shop.id == shop_id,
            Shop.tenant_id == tenant_id,
            Shop.status != "deleted"
        ).first()

        if not shop:
            return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在"}

        shop.status = "deleted"
        db.commit()

        logger.info(f"店铺已删除: shop_id={shop.id}")
        return {"code": ErrorCode.SUCCESS, "data": None}
    except Exception as e:
        db.rollback()
        logger.error(f"删除店铺失败 shop_id={shop_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "删除店铺失败"}


async def test_connection(db: Session, shop_id: int, tenant_id: int) -> dict:
    """测试店铺API连接"""
    try:
        shop = db.query(Shop).filter(
            Shop.id == shop_id,
            Shop.tenant_id == tenant_id,
            Shop.status != "deleted"
        ).first()

        if not shop:
            return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在"}

        if not shop.api_key:
            return {"code": ErrorCode.SHOP_CREDENTIAL_INVALID, "msg": "未配置API凭证"}

        try:
            client = PlatformClientFactory.get_client(
                platform=shop.platform,
                shop_id=shop.id,
                api_key=shop.api_key,
            )
            result = await client.test_connection()
            logger.info(f"店铺连接测试成功: shop_id={shop.id} platform={shop.platform}")
            return {"code": ErrorCode.SUCCESS, "data": {"connected": True, "detail": result}}
        except NotImplementedError:
            # 平台客户端未实现，返回提示
            return {
                "code": ErrorCode.SUCCESS,
                "data": {"connected": False, "detail": f"{shop.platform}平台客户端尚未实现"},
            }
        except Exception as e:
            logger.warning(f"店铺连接测试失败: shop_id={shop.id}: {e}")
            return {
                "code": ErrorCode.SHOP_PLATFORM_ERROR,
                "msg": f"连接测试失败: {str(e)}",
            }
    except Exception as e:
        logger.error(f"测试连接异常 shop_id={shop_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "测试连接异常"}


def _shop_to_dict(shop: Shop) -> dict:
    """将Shop ORM对象转为字典（不暴露敏感凭证）"""
    return {
        "id": shop.id,
        "tenant_id": shop.tenant_id,
        "name": shop.name,
        "platform": shop.platform,
        "platform_seller_id": shop.platform_seller_id,
        "currency": shop.currency,
        "timezone": shop.timezone,
        "status": shop.status,
        "last_sync_at": shop.last_sync_at.isoformat() if shop.last_sync_at else None,
        "created_at": shop.created_at.isoformat() if shop.created_at else None,
        "updated_at": shop.updated_at.isoformat() if shop.updated_at else None,
    }
