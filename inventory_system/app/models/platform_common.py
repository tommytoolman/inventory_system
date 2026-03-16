# platform_common.py
from datetime import datetime, timezone  # noqa: F401
from enum import Enum  # noqa: F401
from typing import Optional  # noqa: F401

from app.core.enums import ListingStatus, SyncStatus
from pydantic import BaseModel  # noqa: F401
from sqlalchemy import JSON, TIMESTAMP, Column, DateTime, ForeignKey, Index, Integer, String, text  # noqa: F401
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from ..database import Base

UTC_NOW = text("now() AT TIME ZONE 'utc'")


class PlatformCommon(Base):
    __tablename__ = "platform_common"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True)
    # created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=UTC_NOW)
    # updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=UTC_NOW)

    created_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"),  # Use standard PG function via text()
        nullable=False,
    )
    updated_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"),  # Use standard PG function via text()
        onupdate=text("timezone('utc', now())"),  # Use standard PG function via text() for ON UPDATE
        nullable=False,
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

    ebay_listing = relationship(
        "EbayListing",
        primaryjoin="and_(PlatformCommon.id == EbayListing.platform_id, EbayListing.listing_status == 'ACTIVE')",
        foreign_keys="EbayListing.platform_id",
        back_populates="platform_listing",
        uselist=False,
        viewonly=True,
    )
    reverb_listing = relationship(
        "ReverbListing",
        primaryjoin="and_(PlatformCommon.id == ReverbListing.platform_id, ReverbListing.reverb_state == 'live')",
        foreign_keys="ReverbListing.platform_id",
        back_populates="platform_listing",
        uselist=False,
        viewonly=True,
    )
    vr_listing = relationship(
        "VRListing",
        primaryjoin="and_(PlatformCommon.id == VRListing.platform_id, VRListing.vr_state == 'active')",
        foreign_keys="VRListing.platform_id",
        back_populates="platform_listing",
        uselist=False,
        viewonly=True,
    )
    shopify_listing = relationship("ShopifyListing", back_populates="platform_listing", uselist=False)
    woocommerce_listing = relationship("WooCommerceListing", back_populates="platform_listing", uselist=False)

    # Unfiltered variants used by the Listing Health report — load any listing record
    # regardless of its live/active state (the filtered variants above exclude drafts/ended).
    reverb_listing_any = relationship(
        "ReverbListing",
        primaryjoin="PlatformCommon.id == ReverbListing.platform_id",
        foreign_keys="ReverbListing.platform_id",
        uselist=False,
        viewonly=True,
        overlaps="reverb_listing",
    )
    ebay_listing_any = relationship(
        "EbayListing",
        primaryjoin="PlatformCommon.id == EbayListing.platform_id",
        foreign_keys="EbayListing.platform_id",
        uselist=False,
        viewonly=True,
        overlaps="ebay_listing",
    )
    vr_listing_any = relationship(
        "VRListing",
        primaryjoin="PlatformCommon.id == VRListing.platform_id",
        foreign_keys="VRListing.platform_id",
        uselist=False,
        viewonly=True,
        overlaps="vr_listing",
    )

    sale = relationship("Sale", back_populates="platform_listing", uselist=False)

    shipments = relationship("Shipment", back_populates="platform_listing")
    orders = relationship("Order", back_populates="platform_listing")
