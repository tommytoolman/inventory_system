"""
Shipping-related database models.
"""

import enum

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Enum, ForeignKey, JSON, Text, text, TIMESTAMP
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base
from app.models.order import Order
from app.core.enums import ShipmentStatus

UTC_NOW = text("now() AT TIME ZONE 'utc'")

class Shipment(Base):
    """Shipment database model"""
    __tablename__ = "shipments"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Core shipment details
    carrier = Column(String, index=True)  # e.g., "dhl", "ups", "fedex"
    carrier_account = Column(String)
    shipment_tracking_number = Column(String, index=True)
    
    # Status tracking
    status = Column(Enum(ShipmentStatus), default=ShipmentStatus.CREATED, index=True)
    # created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=UTC_NOW)
    # updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=UTC_NOW)
    created_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"), # Use standard PG function via text()
        nullable=False
    )
    updated_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"), # Use standard PG function via text()
        onupdate=text("timezone('utc', now())"),      # Use standard PG function via text() for ON UPDATE
        nullable=False
    )
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
  
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=True, index=True)
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
    is_default = Column(Boolean, default=False, nullable=True) # Explicitly nullable if desired, default implies nullable usually
    package_type = Column(String, nullable=True)
    weight = Column(Float, nullable=True)
    dimensions = Column(JSONB, nullable=True)  # Using JSONB for dimensions (length, width, height)
    carriers = Column(JSONB, nullable=True)    # Stores array of carrier codes
    options = Column(JSONB, nullable=True)     # Stores insurance, signature, etc.
    rates = Column(JSONB, nullable=True)       # Stores regional rates
    # created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=UTC_NOW)
    # updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=UTC_NOW)   

    # Corrected Timestamp columns using text() for server-side defaults
    # Assuming you want TIMESTAMP WITHOUT TIME ZONE based on the original error in testing
    created_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"), # Use standard PG function via text()
        nullable=False
    )
    updated_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"), # Use standard PG function via text()
        onupdate=text("timezone('utc', now())"),      # Use standard PG function via text() for ON UPDATE
        nullable=False
    )

    # Relationship to products (Ensure Product model has corresponding relationship)
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