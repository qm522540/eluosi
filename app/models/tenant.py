from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, String, Enum, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import BaseMixin


class Tenant(BaseMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    plan: Mapped[str] = mapped_column(
        Enum("free", "basic", "pro", "enterprise", name="tenant_plan"),
        nullable=False, default="free"
    )
    max_shops: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    status: Mapped[str] = mapped_column(
        Enum("active", "inactive", "deleted", name="tenant_status"),
        nullable=False, default="active"
    )


class User(BaseMixin, Base):
    __tablename__ = "users"

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        Enum("owner", "admin", "operator", "viewer", name="user_role"),
        nullable=False, default="operator"
    )
    wechat_work_userid: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("active", "inactive", "deleted", name="user_status"),
        nullable=False, default="active"
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
