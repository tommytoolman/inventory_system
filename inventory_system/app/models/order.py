# app/models/order.py
from sqlalchemy import Column, Integer, DateTime, String, ForeignKey, text, TIMESTAMP
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from app.database import Base

UTC_NOW = text("now() AT TIME ZONE 'utc'")

class Order(Base):
    """Simple order model to satisfy the foreign key relationship"""
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True)
    order_reference = Column(String)  # External reference number
    # created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=UTC_NOW)
    created_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"), # Use standard PG function via text()
        nullable=False
    )
    # Link to platform_common
    platform_listing_id = Column(Integer, ForeignKey("platform_common.id"), nullable=True, index=True)
    platform_listing = relationship("PlatformCommon", back_populates="orders")
    
    # Reverse relationship to shipments
    shipments = relationship("Shipment", back_populates="order")
