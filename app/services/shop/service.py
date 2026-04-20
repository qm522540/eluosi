"""店铺业务逻辑"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.shop import Shop
from app.models.tenant import Tenant
from app.models.ai_pricing import AiPricingConfig, TimePricingRule
from app.services.platform.base import PlatformClientFactory
from app.utils.errors import ErrorCode
from app.utils.logger import logger


# ==================== 新店配套默认配置（bid_management.md §2.1 / §3.1） ====================

_DEFAULT_AI_CONSERVATIVE = {
    "target_roas": 2.0, "min_roas": 1.5,
    "max_bid": 100, "daily_budget": 500,
    "max_adjust_pct": 15, "gross_margin": 0.5,
}
_DEFAULT_AI_DEFAULT = {
    "target_roas": 3.0, "min_roas": 1.8,
    "max_bid": 180, "daily_budget": 2000,
    "max_adjust_pct": 30, "gross_margin": 0.5,
}
_DEFAULT_AI_AGGRESSIVE = {
    "target_roas": 4.0, "min_roas": 2.5,
    "max_bid": 300, "daily_budget": 0,
    "max_adjust_pct": 25, "gross_margin": 0.5,
}
_DEFAULT_TIME_PEAK_HOURS = [10, 11, 12, 13, 19, 20, 21, 22]
_DEFAULT_TIME_MID_HOURS = [7, 8, 9, 14, 15, 16, 17, 18]
_DEFAULT_TIME_LOW_HOURS = [0, 1, 2, 3, 4, 5, 6, 23]


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
        db.flush()  # 拿到 shop.id 但不 commit，确保配套行与店铺同原子

        # 配套默认配置：AI 调价 + 分时调价（避免 ai_pricing_executor 里"配置不存在"报错）
        db.add(AiPricingConfig(
            shop_id=shop.id, tenant_id=tenant_id,
            is_active=0, auto_execute=0, template_name="default",
            conservative_config=_DEFAULT_AI_CONSERVATIVE,
            default_config=_DEFAULT_AI_DEFAULT,
            aggressive_config=_DEFAULT_AI_AGGRESSIVE,
        ))
        db.add(TimePricingRule(
            shop_id=shop.id, tenant_id=tenant_id, is_active=0,
            peak_hours=_DEFAULT_TIME_PEAK_HOURS,
            mid_hours=_DEFAULT_TIME_MID_HOURS,
            low_hours=_DEFAULT_TIME_LOW_HOURS,
            peak_ratio=120, mid_ratio=100, low_ratio=60,
        ))

        db.commit()
        db.refresh(shop)

        logger.info(f"店铺创建成功: shop_id={shop.id} platform={shop.platform} tenant_id={tenant_id}（含配套 AI/分时默认配置）")
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


def _iso_utc(dt: datetime | None) -> str | None:
    """把数据库的 naive datetime 当作 UTC 输出 ISO 字符串（带 +00:00 后缀）。

    DB 列是 naive DateTime，但项目约定写入时存的就是 UTC clock。
    前端 new Date(str) 对无时区后缀的 ISO 串会按本地时区解析，导致 8 小时偏差。
    在边界统一附加 UTC tz。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _shop_to_dict(shop: Shop) -> dict:
    """将Shop ORM对象转为字典（不暴露敏感凭证）

    yandex_business_id / yandex_campaign_id 不算敏感（不能用来直接调 API），
    平显示给用户便于编辑确认，跟 client_id 同等级。
    """
    return {
        "id": shop.id,
        "tenant_id": shop.tenant_id,
        "name": shop.name,
        "platform": shop.platform,
        "platform_seller_id": shop.platform_seller_id,
        "client_id": shop.client_id,
        "perf_client_id": shop.perf_client_id,
        "yandex_business_id": shop.yandex_business_id,
        "yandex_campaign_id": shop.yandex_campaign_id,
        "currency": shop.currency,
        "timezone": shop.timezone,
        "status": shop.status,
        "last_sync_at": _iso_utc(shop.last_sync_at),
        "created_at": _iso_utc(shop.created_at),
        "updated_at": _iso_utc(shop.updated_at),
    }
