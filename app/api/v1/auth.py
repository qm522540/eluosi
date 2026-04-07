"""认证路由"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.schemas.auth import LoginRequest, RegisterRequest, ChangePasswordRequest
from app.services.auth.service import (
    authenticate_user,
    register_user,
    get_user_info,
    refresh_token,
    change_password,
)
from app.utils.response import success, error

router = APIRouter()


@router.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    """用户登录"""
    result = authenticate_user(db, req.email, req.password)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.post("/register")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """注册新用户（同时创建租户）"""
    result = register_user(db, req.username, req.email, req.password, req.tenant_name)
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"], msg="注册成功")


@router.get("/me")
def me(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取当前登录用户信息"""
    result = get_user_info(db, current_user["user_id"], current_user["tenant_id"])
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])


@router.put("/change-password")
def update_password(
    req: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """修改密码"""
    result = change_password(
        db, current_user["user_id"], current_user["tenant_id"],
        req.old_password, req.new_password
    )
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(msg="密码修改成功")


@router.post("/refresh")
def refresh(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """刷新JWT令牌"""
    result = refresh_token(
        db, current_user["user_id"], current_user["tenant_id"], current_user["role"]
    )
    if result["code"] != 0:
        return error(result["code"], result["msg"])
    return success(result["data"])
