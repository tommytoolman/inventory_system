# app.models.vr.py
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any

from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, text, TIMESTAMP, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
# from app.database import Base # Assuming your Base is in app.database

from ..database import Base

UTC_NOW = text("now() AT TIME ZONE 'utc'")

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

    # Add enhanced fields (similar to ReverbListing)
    vr_listing_id = Column(String)  # ID assigned by V&R
    inventory_quantity = Column(Integer, default=1)
    vr_state = Column(String)  # Status on V&R
    last_synced_at = Column(DateTime)
    
    # Optional: Flexible storage for other attributes
    extended_attributes = Column(JSONB, default={})

    # Relationships
    platform_listing = relationship("PlatformCommon", back_populates="vr_listing")

class VRAcceptedBrand(Base):
    __tablename__ = "vr_accepted_brands"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True) # Your internal DB PK
    vr_brand_id = Column(Integer, nullable=True, unique=True, index=True) # V&R's own ID for the brand, can be null
    name = Column(String, nullable=False, unique=True, index=True)
    name_normalized = Column(String, nullable=False, unique=True, index=True) # For case-insensitive lookups

    # Optional: Add a UniqueConstraint if vr_brand_id should be unique when not null
    # __table_args__ = (UniqueConstraint('vr_brand_id', name='uq_vr_brand_id_not_null'),)
    # However, SQLAlchemy and PostgreSQL handle unique=True on nullable columns well.

    def __repr__(self):
        return f"<VRAcceptedBrand(id={self.id}, name='{self.name}', vr_brand_id={self.vr_brand_id})>"
    
