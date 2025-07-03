# platform_common.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, text, TIMESTAMP
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel

from ..database import Base

from app.core.enums import ListingStatus, SyncStatus

UTC_NOW = text("now() AT TIME ZONE 'utc'")

class PlatformCommon(Base):
    __tablename__ = "platform_common"

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
    
    product_id = Column(Integer, ForeignKey("products.id"), index=True, nullable=False)
    platform_name = Column(String)
    external_id = Column(String)
    status = Column(String, default=ListingStatus.DRAFT, index=True)
    last_sync = Column(DateTime)
    sync_status = Column(String, default=SyncStatus.PENDING, index=True)
    listing_url = Column(String)
    platform_specific_data = Column(JSONB, default={})

    # Relationships
    product = relationship("Product", back_populates="platform_listings")
    
    ebay_listing = relationship("EbayListing", back_populates="platform_listing", uselist=False)
    reverb_listing = relationship("ReverbListing", back_populates="platform_listing", uselist=False)
    vr_listing = relationship("VRListing", back_populates="platform_listing", uselist=False)
    shopify_listing = relationship("ShopifyListing", back_populates="platform_listing", uselist=False)
    
    sale = relationship("Sale", back_populates="platform_listing", uselist=False)
    
    shipments = relationship("Shipment", back_populates="platform_listing")
    orders = relationship("Order", back_populates="platform_listing")