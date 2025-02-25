# Example for vr.py
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any

from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB

from ..database import Base

class VRListing(Base):
    __tablename__ = "vr_listings"

    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platform_common.id"))
    
    # V&R specific fields
    in_collective = Column(Boolean, default=False)
    in_inventory = Column(Boolean, default=True)
    in_reseller = Column(Boolean, default=False)
    collective_discount = Column(Float)
    price_notax = Column(Float)
    show_vat = Column(Boolean, default=True)
    processing_time = Column(Integer)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_synced_at = Column(DateTime)


    # Relationships
    platform_listing = relationship("PlatformCommon", back_populates="vr_listing")