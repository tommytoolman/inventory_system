"""
Shipping-related database models.
"""

import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Enum, ForeignKey, JSON, Text, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base
from app.models.order import Order

class ShipmentStatus(enum.Enum):
    """Shipment status enum"""
    CREATED = "created"
    LABEL_CREATED = "label_created"
    PICKED_UP = "picked_up"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    EXCEPTION = "exception"
    CANCELLED = "cancelled"

class Shipment(Base):
    """Shipment database model"""
    __tablename__ = "shipments"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Core shipment details
    carrier = Column(String, index=True)  # e.g., "dhl", "ups", "fedex"
    carrier_account = Column(String)
    shipment_tracking_number = Column(String, index=True)
    
    # Status tracking
    status = Column(Enum(ShipmentStatus), default=ShipmentStatus.CREATED)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Shipment details
    origin_address = Column(JSON)  # Store as JSON for flexibility
    destination_address = Column(JSON)
    
    # Package details
    package_weight = Column(Float)
    package_length = Column(Float)
    package_width = Column(Float)
    package_height = Column(Float)
    package_description = Column(String)
    is_international = Column(Boolean, default=False)
    
    # References
    reference_number = Column(String, index=True)
    
    # Customs information for international shipments
    customs_value = Column(Float, nullable=True)
    customs_currency = Column(String, nullable=True)
    
    # Response data
    carrier_response = Column(JSON, nullable=True)  # Store full API response
    label_data = Column(Text, nullable=True)  # Base64 encoded label data
    label_format = Column(String, nullable=True)  # e.g., "pdf", "png"
    
    # User reference (optional)
    # user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # user = relationship("User", back_populates="shipments")
    
    # Order reference (optional)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    order = relationship("Order", back_populates="shipments")
  
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=True)
    sale = relationship("Sale", back_populates="shipments")
    
    # Remove order_id and replace with platform_listing_id
    platform_listing_id = Column(Integer, ForeignKey("platform_common.id"), nullable=True)
    platform_listing = relationship("PlatformCommon", back_populates="shipments")
    
    def __repr__(self):
        return f"<Shipment {self.id}: {self.carrier} - {self.shipment_tracking_number}>"

class ShippingProfile(Base):
    __tablename__ = "shipping_profiles"
    
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    is_default = Column(Boolean, default=False)
    package_type = Column(String, nullable=True)
    weight = Column(Float, nullable=True)
    dimensions = Column(JSONB, nullable=True)  # Using JSONB for dimensions (length, width, height)
    carriers = Column(JSONB, nullable=True)    # Stores array of carrier codes
    options = Column(JSONB, nullable=True)     # Stores insurance, signature, etc.
    rates = Column(JSONB, nullable=True)       # Stores regional rates
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationship to products
    products = relationship("Product", back_populates="shipping_profile")
    
    # Properties to maintain backward compatibility
    @property
    def length(self):
        """Get length from dimensions JSON"""
        return self.dimensions.get('length') if self.dimensions else None
        
    @property
    def width(self):
        """Get width from dimensions JSON"""
        return self.dimensions.get('width') if self.dimensions else None
        
    @property
    def height(self):
        """Get height from dimensions JSON"""
        return self.dimensions.get('height') if self.dimensions else None