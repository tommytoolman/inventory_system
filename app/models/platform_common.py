# platform_common.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel

from ..database import Base

class SyncStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress" 
    SUCCESS = "success"
    ERROR = "error"
    FAILED = "failed"

class ListingStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ENDED = "ended"
    DELETED = "deleted"

class PlatformCommon(Base):
    __tablename__ = "platform_common"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    product_id = Column(Integer, ForeignKey("products.id"))
    platform_name = Column(String)
    external_id = Column(String)
    status = Column(String, default=ListingStatus.DRAFT)
    last_sync = Column(DateTime)
    sync_status = Column(String, default=SyncStatus.PENDING)
    listing_url = Column(String)
    platform_specific_data = Column(JSONB, default={})

    # Relationships
    product = relationship("Product", back_populates="platform_listings")
    ebay_listing = relationship("EbayListing", back_populates="platform_listing", uselist=False)
    reverb_listing = relationship("ReverbListing", back_populates="platform_listing", uselist=False)
    vr_listing = relationship("VRListing", back_populates="platform_listing", uselist=False)
    website_listing = relationship("WebsiteListing", back_populates="platform_listing", uselist=False)
    sale = relationship("Sale", back_populates="platform_listing", uselist=False)