"""认证业务逻辑"""

import re
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.tenant import Tenant, User
from app.utils.security import hash_password, verify_password, create_access_token
from app.utils.errors import ErrorCode
from app.utils.logger import logger

settings = get_settings()


def authenticate_user(db: Session, email: str, password: str) -> dict:
    """用户登录认证

    Returns:
        {"code": 0, "data": {"access_token": ..., "user": ...}} 或错误dict
    """
    try:
        user = db.query(User).filter(
            User.email == email,
            User.status == "active"
        ).first()

        if not user or not verify_password(password, user.password_hash):
            logger.warning(f"登录失败: email={email}")
            return {"code": ErrorCode.AUTH_FAILED, "msg": "邮箱或密码错误"}

        # 生成JWT
        token_data = {
            "user_id": user.id,
            "tenant_id": user.tenant_id,
            "role": user.role,
        }
        access_token = create_access_token(token_data)

        # 更新最后登录时间
        user.last_login_at = datetime.utcnow()
        db.commit()

        logger.info(f"用户登录成功: user_id={user.id} tenant_id={user.tenant_id}")
        return {
            "code": ErrorCode.SUCCESS,
            "data": {
                "access_token": access_token,
                "token_type": "bearer",
                "expires_in": settings.JWT_EXPIRE_MINUTES * 60,
                "user": {
                    "id": user.id,
                    "tenant_id": user.tenant_id,
                    "username": user.username,
                    "email": user.email,
                    "role": user.role,
                    "status": user.status,
                },
            },
        }
    except Exception as e:
        logger.error(f"登录异常: email={email}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "登录服务异常"}


def register_user(db: Session, username: str, email: str, password: str, tenant_name: str) -> dict:
    """注册新用户（同时创建租户）

    Returns:
        {"code": 0, "data": {...}} 或错误dict
    """
    try:
        # 检查邮箱是否已存在
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            return {"code": ErrorCode.PARAM_ERROR, "msg": "该邮箱已被注册"}

        # 生成租户slug
        slug = re.sub(r'[^a-zA-Z0-9]', '-', tenant_name.lower()).strip('-')
        existing_tenant = db.query(Tenant).filter(Tenant.slug == slug).first()
        if existing_tenant:
            slug = f"{slug}-{int(datetime.utcnow().timestamp())}"

        # 创建租户
        tenant = Tenant(
            name=tenant_name,
            slug=slug,
            plan="free",
            max_shops=3,
            status="active",
        )
        db.add(tenant)
        db.flush()  # 获取tenant.id

        # 创建用户（owner角色）
        user = User(
            tenant_id=tenant.id,
            username=username,
            email=email,
            password_hash=hash_password(password),
            role="owner",
            status="active",
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        logger.info(f"新用户注册: user_id={user.id} tenant_id={tenant.id} email={email}")
        return {
            "code": ErrorCode.SUCCESS,
            "data": {
                "user_id": user.id,
                "tenant_id": tenant.id,
                "username": user.username,
                "email": user.email,
                "role": user.role,
            },
        }
    except Exception as e:
        db.rollback()
        logger.error(f"注册异常: email={email}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "注册服务异常"}


def get_user_info(db: Session, user_id: int, tenant_id: int) -> dict:
    """获取当前用户信息"""
    try:
        user = db.query(User).filter(
            User.id == user_id,
            User.tenant_id == tenant_id,
            User.status == "active"
        ).first()

        if not user:
            return {"code": ErrorCode.NOT_FOUND, "msg": "用户不存在"}

        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()

        return {
            "code": ErrorCode.SUCCESS,
            "data": {
                "id": user.id,
                "tenant_id": user.tenant_id,
                "username": user.username,
                "email": user.email,
                "role": user.role,
                "status": user.status,
                "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
                "tenant": {
                    "id": tenant.id,
                    "name": tenant.name,
                    "plan": tenant.plan,
                    "max_shops": tenant.max_shops,
                } if tenant else None,
            },
        }
    except Exception as e:
        logger.error(f"获取用户信息异常: user_id={user_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取用户信息异常"}


def refresh_token(db: Session, user_id: int, tenant_id: int, role: str) -> dict:
    """刷新JWT令牌"""
    try:
        # 验证用户仍然有效
        user = db.query(User).filter(
            User.id == user_id,
            User.tenant_id == tenant_id,
            User.status == "active"
        ).first()

        if not user:
            return {"code": ErrorCode.AUTH_FAILED, "msg": "用户不存在或已停用"}

        token_data = {
            "user_id": user.id,
            "tenant_id": user.tenant_id,
            "role": user.role,
        }
        access_token = create_access_token(token_data)

        return {
            "code": ErrorCode.SUCCESS,
            "data": {
                "access_token": access_token,
                "token_type": "bearer",
                "expires_in": settings.JWT_EXPIRE_MINUTES * 60,
            },
        }
    except Exception as e:
        logger.error(f"刷新令牌异常: user_id={user_id}: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "刷新令牌异常"}
