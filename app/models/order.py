# app/models/order.py
from sqlalchemy import Column, Integer, DateTime, String, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from app.database import Base

class Order(Base):
    """Simple order model to satisfy the foreign key relationship"""
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True)
    order_reference = Column(String)  # External reference number
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Link to platform_common
    platform_listing_id = Column(Integer, ForeignKey("platform_common.id"), nullable=True)
    platform_listing = relationship("PlatformCommon", back_populates="orders")
    
    # Reverse relationship to shipments
    shipments = relationship("Shipment", back_populates="order")
