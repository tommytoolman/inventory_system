# platform_common.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel

from ..database import Base

from app.core.enums import ListingStatus, SyncStatus

class PlatformCommon(Base):
    __tablename__ = "platform_common"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
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
    
    shipments = relationship("Shipment", back_populates="platform_listing")
    orders = relationship("Order", back_populates="platform_listing")