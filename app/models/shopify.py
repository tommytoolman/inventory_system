# app/models/shopify.py (corrected)
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any

from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, text, TIMESTAMP
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB

from ..database import Base

UTC_NOW = text("now() AT TIME ZONE 'utc'")

class ShopifyListing(Base):
    __tablename__ = "shopify_listings"  # FIXED: was "shopfiy_listings"

    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platform_common.id"))
    
    # NEW: Shopify product identifiers
    shopify_product_id = Column(String(50), nullable=True, index=True)  # GID
    shopify_legacy_id = Column(String(20), nullable=True, index=True)   # Numeric ID
    handle = Column(String(255), nullable=True, index=True)
    title = Column(String(255), nullable=True)
    vendor = Column(String(255), nullable=True)
    status = Column(String(20), nullable=True)  # ACTIVE, DRAFT, ARCHIVED
    price = Column(Float, nullable=True)
    
    # NEW: Category fields
    category_gid = Column(String(100), nullable=True, index=True)
    category_name = Column(String(255), nullable=True)
    category_full_name = Column(String(500), nullable=True)
    category_assigned_at = Column(DateTime, nullable=True)
    category_assignment_status = Column(String(20), nullable=True)  # PENDING, ASSIGNED, FAILED
    
    # EXISTING: Shopify specific fields
    seo_title = Column(String)
    seo_description = Column(String)
    seo_keywords = Column(JSONB)
    featured = Column(Boolean, default=False)
    custom_layout = Column(String)
    
    last_synced_at = Column(DateTime)
    
    created_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"),
        nullable=False
    )
    updated_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"),
        onupdate=text("timezone('utc', now())"),
        nullable=False
    )
    
    # Add this field to ShopifyListing class:
    extended_attributes = Column(JSONB, nullable=True)
    
    # Relationships
    platform_listing = relationship("PlatformCommon", back_populates="shopify_listing")