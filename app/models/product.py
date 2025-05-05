"""
Models for the inventory management system's core functionality.

This module contains SQLAlchemy models for products and their platform-specific listings.
It provides the database structure for storing product information and tracking how these
products are listed across different e-commerce platforms.
"""

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Enum, ForeignKey, text, TIMESTAMP
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB, ENUM
from pydantic import BaseModel, Field, validator
from enum import Enum
from datetime import datetime, timezone
import enum
from ..database import Base

from app.core.enums import ProductStatus, ProductCondition
from app.models.shipping import ShippingProfile
from sqlalchemy.dialects.postgresql import JSONB

UTC_NOW = text("now() AT TIME ZONE 'utc'")

class Product(Base):
    __tablename__ = "products"

    # Primary Key and Timestamps
    id = Column(Integer, primary_key=True)
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
    
    # Core Product Information
    sku = Column(String, unique=True)
    brand = Column(String)
    model = Column(String)
    year = Column(Integer)
    decade = Column(Integer)
    finish = Column(String)
    category = Column(String)
    condition = Column(ENUM(ProductCondition, name='productcondition', create_type=True), nullable=False)
    description = Column(String)
    
    # Pricing Fields
    base_price = Column(Float)
    cost_price = Column(Float)
    price = Column(Float)
    price_notax = Column(Float)
    collective_discount = Column(Float)
    offer_discount = Column(Float)
    
    # Status and Flags
    status = Column(ENUM(ProductStatus, name='productstatus', create_type=True), default=ProductStatus.DRAFT.value, index=True)
    is_sold = Column(Boolean, default=False)
    in_collective = Column(Boolean, default=False)
    in_inventory = Column(Boolean, default=True)
    in_reseller = Column(Boolean, default=False)
    free_shipping = Column(Boolean, default=False)
    buy_now = Column(Boolean, default=True)
    show_vat = Column(Boolean, default=True)
    local_pickup = Column(Boolean, default=False)
    available_for_shipment = Column(Boolean, default=True)
    
    # Media and Links
    primary_image = Column(String)
    additional_images = Column(JSONB, default=list)
    video_url = Column(String)
    external_link = Column(String)
    
    # Additional Fields
    processing_time = Column(Integer)
    # platform_data = Column(JSONB, default=dict) # Mark for removal. Think this is now redundant.
    
    # Shipping
    shipping_profile_id = Column(Integer, ForeignKey('shipping_profiles.id'), nullable=True)
    package_type = Column(String, nullable=True)
    package_weight = Column(Float, nullable=True)
    package_dimensions = Column(JSONB, nullable=True)  # Using JSONB for dimensions


    #####################################################
    ################## Relationships ####################
    #####################################################

    platform_listings = relationship("PlatformCommon", back_populates="product")
    sales = relationship("Sale", back_populates="product")
    shipping_profile = relationship("ShippingProfile", back_populates="products")
    