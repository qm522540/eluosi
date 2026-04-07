"""认证模块 Pydantic 数据模型"""

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: str = Field(..., description="邮箱")
    password: str = Field(..., min_length=6, description="密码")


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50, description="用户名")
    email: str = Field(..., description="邮箱")
    password: str = Field(..., min_length=6, max_length=128, description="密码")
    tenant_name: str = Field(..., min_length=2, max_length=100, description="公司/品牌名称")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserInfo(BaseModel):
    id: int
    tenant_id: int
    username: str
    email: str
    role: str
    status: str

    model_config = {"from_attributes": True}
