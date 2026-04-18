from datetime import date, datetime
from sqlalchemy import BigInteger, String, Integer, DECIMAL, Date, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OzonProductQuery(Base):
    """Ozon SKU × 搜索词维度数据（来源 /v1/analytics/product-queries/details）

    数据是 SEO 自然 + 广告综合（不区分），含完整漏斗：
    曝光 → 点击 → 加购 → 订单 → 营收。

    UNIQUE: (tenant_id, shop_id, sku, query, stat_date)
    """
    __tablename__ = "ozon_product_queries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sku: Mapped[str] = mapped_column(String(50), nullable=False)
    query: Mapped[str] = mapped_column(String(500), nullable=False)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    add_to_cart: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revenue: Mapped[float] = mapped_column(DECIMAL(12, 2), nullable=False, default=0)
    frequency: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    view_conversion: Mapped[float] = mapped_column(DECIMAL(8, 4), nullable=False, default=0)
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
