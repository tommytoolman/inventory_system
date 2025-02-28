"""
ReverbListing Model

This model represents a listing on the Reverb platform. It extends the base
platform_common model with Reverb-specific attributes.
"""
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any

from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base

class ReverbListing(Base):
    __tablename__ = "reverb_listings"

    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platform_common.id"))
    
    # Reverb specific fields
    reverb_category_uuid = Column(String)
    condition_rating = Column(Float)
    shipping_profile_id = Column(String)
    shop_policies_id = Column(String)
    handmade = Column(Boolean, default=False)
    offers_enabled = Column(Boolean, default=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_synced_at = Column(DateTime)
    
    # Relationships
    platform_listing = relationship("PlatformCommon", back_populates="reverb_listing")    
class ReverbListing(Base):
    """
    Model for Reverb platform listings.
    
    This table stores Reverb-specific attributes for listings, linked to the
    platform_common table for shared attributes across platforms.
    """
    __tablename__ = "reverb_listings"

    # Primary key and relationship
    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platform_common.id"))
    
    # Reverb-specific fields
    reverb_listing_id = Column(String)  # ID assigned by Reverb
    reverb_category_uuid = Column(String)  # UUID of category in Reverb's system
    condition_rating = Column(Float)  # Condition rating as float (1-5)
    shipping_profile_id = Column(String)  # ID of shipping profile in Reverb
    shop_policies_id = Column(String)  # ID of shop policies in Reverb
    handmade = Column(Boolean, default=False)  # Is this a handmade item?
    offers_enabled = Column(Boolean, default=True)  # Are offers enabled?
    
    # Tracking fields
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_synced_at = Column(DateTime)  # Last time this was synced with Reverb
    
    # Relationships
    platform_listing = relationship("PlatformCommon", back_populates="reverb_listing")
