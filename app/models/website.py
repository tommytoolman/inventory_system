from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any

from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB

from ..database import Base

class WebsiteListing(Base):
    __tablename__ = "website_listings"

    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platform_common.id"))
    
    # Website specific fields
    seo_title = Column(String)
    seo_description = Column(String)
    seo_keywords = Column(JSONB)
    featured = Column(Boolean, default=False)
    custom_layout = Column(String)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_synced_at = Column(DateTime)
    
    # Relationships
    platform_listing = relationship("PlatformCommon", back_populates="website_listing")