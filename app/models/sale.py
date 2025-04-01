# app/models/sale.py

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime
from ..database import Base

class Sale(Base):
    __tablename__ = "sales"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relations
    product_id = Column(Integer, ForeignKey("products.id"))
    platform_listing_id = Column(Integer, ForeignKey("platform_common.id"))
    
    # Sale details
    platform_name = Column(String)  # ebay, reverb, vintageandrare
    sale_date = Column(DateTime, default=datetime.utcnow)
    sale_price = Column(Float)
    original_list_price = Column(Float)
    platform_fees = Column(Float)
    shipping_cost = Column(Float)
    net_amount = Column(Float)
    
    # Additional info
    days_to_sell = Column(Integer)  # Calculated from listing creation to sale
    payment_method = Column(String)
    shipping_method = Column(String)
    buyer_location = Column(String)
    
    # Platform-specific data (like eBay order ID, Reverb order details)
    platform_data = Column(JSONB, default={})
    
    # Relationships
    product = relationship("Product", back_populates="sales")
    platform_listing = relationship("PlatformCommon", back_populates="sale")
    shipments = relationship("Shipment", back_populates="sale")    