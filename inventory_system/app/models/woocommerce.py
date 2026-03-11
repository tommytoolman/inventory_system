# app/models/woocommerce.py
"""
WooCommerce Listing Model

This model represents a listing on a WooCommerce store, linked to the
platform_common table for shared attributes across platforms.
Follows the same pattern as ShopifyListing / ReverbListing.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, text, TIMESTAMP
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB

from ..database import Base


class WooCommerceListing(Base):
    """
    Model for WooCommerce platform listings.

    Links to platform_common via platform_id for shared product linkage.
    Stores WooCommerce-specific attributes for each listing.
    """
    __tablename__ = "woocommerce_listings"

    # Primary key and relationship
    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platform_common.id"), index=True)

    # Multi-tenant: optional link to WooCommerceStore (nullable for backward compat)
    wc_store_id = Column(Integer, ForeignKey("woocommerce_stores.id"), nullable=True, index=True)

    # Core WooCommerce identifiers
    wc_product_id = Column(String(50), nullable=True, index=True)  # WooCommerce product ID
    slug = Column(String(255), nullable=True, index=True)  # URL slug
    permalink = Column(String(500), nullable=True)

    # Product info
    title = Column(String(255), nullable=True)
    status = Column(String(20), nullable=True)  # publish, draft, pending, private
    product_type = Column(String(50), nullable=True)  # simple, grouped, external, variable
    sku = Column(String(100), nullable=True, index=True)

    # Pricing
    regular_price = Column(Float, nullable=True)
    sale_price = Column(Float, nullable=True)
    price = Column(Float, nullable=True)  # Current effective price

    # Inventory
    manage_stock = Column(Boolean, default=True)
    stock_quantity = Column(Integer, nullable=True)
    stock_status = Column(String(20), nullable=True)  # instock, outofstock, onbackorder

    # Category
    category_id = Column(String(50), nullable=True)
    category_name = Column(String(255), nullable=True)

    # Shipping
    weight = Column(String(20), nullable=True)
    shipping_class = Column(String(100), nullable=True)

    # Stats
    total_sales = Column(Integer, default=0)

    # Timestamps from WooCommerce
    wc_created_at = Column(DateTime, nullable=True)
    wc_modified_at = Column(DateTime, nullable=True)

    # Local timestamps
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
    last_synced_at = Column(DateTime, nullable=True)

    # Flexible storage for full WooCommerce API response
    extended_attributes = Column(JSONB, nullable=True)

    # Relationships
    platform_listing = relationship("PlatformCommon", back_populates="woocommerce_listing")
    wc_store = relationship("WooCommerceStore", back_populates="listings")
