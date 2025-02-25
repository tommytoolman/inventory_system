# Example for reverb.py
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any

from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB

from ..database import Base

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
