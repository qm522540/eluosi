from typing import Generator
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import jwt, JWTError

from app.database import SessionLocal
from app.config import get_settings

security = HTTPBearer()
settings = get_settings()


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        user_id: int = payload.get("user_id")
        tenant_id: int = payload.get("tenant_id")
        if user_id is None or tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的认证令牌"
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="认证令牌已过期或无效"
        )
    return {"user_id": user_id, "tenant_id": tenant_id, "role": payload.get("role")}


def get_tenant_id(current_user: dict = Depends(get_current_user)) -> int:
    return current_user["tenant_id"]


def get_owned_shop(
    shop_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    """多租户隔离守卫：所有带 {shop_id} 路径参数的接口必须用此 Depends

    校验 shop 存在 + 属于当前租户。任意一项不通过返回 404。
    Returns: Shop 模型对象（路由内部用 shop.id / shop.tenant_id）。
    """
    from app.models.shop import Shop

    shop = db.query(Shop).filter(
        Shop.id == shop_id,
        Shop.tenant_id == tenant_id,
    ).first()
    if not shop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="店铺不存在或无访问权限",
        )
    return shop
