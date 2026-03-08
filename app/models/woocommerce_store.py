# app/models/woocommerce_store.py
"""Per-tenant WooCommerce store configuration.

Stores the connection credentials and settings for each retailer's
WooCommerce store. Falls back to environment variables if no store
record exists (backward compatibility with single-tenant deployment).
"""

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, text, TIMESTAMP
from sqlalchemy.orm import relationship

from ..database import Base


class WooCommerceStore(Base):
    """Per-retailer WooCommerce store credentials and configuration."""

    __tablename__ = "woocommerce_stores"

    id = Column(Integer, primary_key=True)

    # Human-readable label (e.g. "Rockers Guitars WC Store")
    name = Column(String(255), nullable=False)

    # Connection credentials
    store_url = Column(String(500), nullable=False)
    consumer_key = Column(String(255), nullable=False)
    consumer_secret = Column(String(255), nullable=False)

    # Webhook secret for signature verification (per-store)
    webhook_secret = Column(String(255), nullable=True, default="")

    # Pricing
    price_markup_percent = Column(Float, default=0.0, nullable=False)

    # Store health
    is_active = Column(Boolean, default=True, nullable=False)
    sync_status = Column(String(20), default="healthy", nullable=False)  # healthy, error, disconnected
    last_sync_at = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"),
        nullable=False,
    )
    updated_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"),
        onupdate=text("timezone('utc', now())"),
        nullable=False,
    )

    # Relationships
    listings = relationship("WooCommerceListing", back_populates="wc_store", lazy="dynamic")
    orders = relationship("WooCommerceOrder", back_populates="wc_store", lazy="dynamic")
