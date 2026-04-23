"""商品被搜索词每日统计模型（搜索词洞察 / SEO 流量）

数据源：
- WB   POST /api/v2/search-report/product/search-texts（需 Jam 订阅）
- Ozon POST /v1/analytics/product-queries/details   （需 Premium 订阅）

字段按两平台并集，平台特有字段存 extra JSON。
"""

from datetime import datetime, date
from typing import Optional
from sqlalchemy import BigInteger, String, Enum, Integer, DECIMAL, Date, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils.moscow_time import utc_now_naive


class ProductSearchQuery(Base):
    __tablename__ = "product_search_queries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform: Mapped[str] = mapped_column(Enum("wb", "ozon", name="psq_platform"), nullable=False)
    platform_sku_id: Mapped[str] = mapped_column(String(100), nullable=False)
    product_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    query_text: Mapped[str] = mapped_column(String(500), nullable=False)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False)
    frequency: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    add_to_cart: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revenue: Mapped[float] = mapped_column(DECIMAL(12, 2), nullable=False, default=0)
    median_position: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 2), nullable=True)
    cart_to_order: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4), nullable=True)
    view_conversion: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4), nullable=True)
    extra: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=utc_now_naive,
    )
