# app/models/order.py
from datetime import datetime, timezone  # noqa: F401

from app.database import Base
from sqlalchemy import TIMESTAMP, Column, DateTime, ForeignKey, Integer, String, text  # noqa: F401
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

UTC_NOW = text("now() AT TIME ZONE 'utc'")


class Order(Base):
    """Simple order model to satisfy the foreign key relationship"""

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True)
    order_reference = Column(String)  # External reference number
    # created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=UTC_NOW)
    created_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"),  # Use standard PG function via text()
        nullable=False,
    )
    # Link to platform_common
    platform_listing_id = Column(Integer, ForeignKey("platform_common.id"), nullable=True, index=True)
    platform_listing = relationship("PlatformCommon", back_populates="orders")

    # Reverse relationship to shipments
    shipments = relationship("Shipment", back_populates="order")
