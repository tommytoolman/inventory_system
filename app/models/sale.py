# app/models/sale.py

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, text, TIMESTAMP
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime, timezone
from ..database import Base

UTC_NOW = text("now() AT TIME ZONE 'utc'")

class Sale(Base):
    __tablename__ = "sales"

    id = Column(Integer, primary_key=True)
    # created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=UTC_NOW)
    
    created_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"), # Use standard PG function via text()
        nullable=False
    )
    
    # Relations
    product_id = Column(Integer, ForeignKey("products.id"), index=True, nullable=False)
    platform_listing_id = Column(Integer, ForeignKey("platform_common.id"), index=True, nullable=False)
    
    # Sale details
    platform_name = Column(String)  # ebay, reverb, vintageandrare
    # sale_date = Column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=UTC_NOW)
    sale_date = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"), # Use standard PG function via text()
        onupdate=text("timezone('utc', now())"),      # Use standard PG function via text() for ON UPDATE
        nullable=False
    )
    
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