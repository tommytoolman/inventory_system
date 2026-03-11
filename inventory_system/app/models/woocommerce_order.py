# app/models/woocommerce_order.py
"""
WooCommerce Order Model

Tracks orders received from WooCommerce, following the same pattern
as ReverbOrder and ShopifyOrder.
"""

from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, text, TIMESTAMP
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB

from ..database import Base


class WooCommerceOrder(Base):
    """
    Model for WooCommerce orders.
    Stores order data received via API polling or webhooks.
    """
    __tablename__ = "woocommerce_orders"

    id = Column(Integer, primary_key=True)

    # Multi-tenant: optional link to WooCommerceStore (nullable for backward compat)
    wc_store_id = Column(Integer, ForeignKey("woocommerce_stores.id"), nullable=True, index=True)

    # WooCommerce order identifiers
    wc_order_id = Column(String(50), unique=True, nullable=False, index=True)
    order_number = Column(String(50), nullable=True)
    order_key = Column(String(100), nullable=True)

    # Order status
    status = Column(String(30), nullable=True)  # pending, processing, on-hold, completed, etc.
    payment_method = Column(String(50), nullable=True)
    payment_method_title = Column(String(100), nullable=True)

    # Customer info
    customer_id = Column(String(50), nullable=True)
    customer_name = Column(String(200), nullable=True)
    customer_email = Column(String(255), nullable=True)

    # Shipping address
    shipping_name = Column(String(200), nullable=True)
    shipping_address_1 = Column(String(255), nullable=True)
    shipping_address_2 = Column(String(255), nullable=True)
    shipping_city = Column(String(100), nullable=True)
    shipping_state = Column(String(50), nullable=True)
    shipping_postcode = Column(String(20), nullable=True)
    shipping_country = Column(String(10), nullable=True)

    # Pricing
    total = Column(Float, nullable=True)
    subtotal = Column(Float, nullable=True)
    shipping_total = Column(Float, nullable=True)
    tax_total = Column(Float, nullable=True)
    discount_total = Column(Float, nullable=True)
    currency = Column(String(10), nullable=True)

    # Line items (stored as JSON)
    line_items = Column(JSONB, nullable=True)

    # RIFF linkage
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    platform_listing_id = Column(Integer, ForeignKey("platform_common.id"), nullable=True)

    # Processing flag
    sale_processed = Column(Boolean, default=False)

    # Full raw payload for audit
    raw_payload = Column(JSONB, nullable=True)

    # Timestamps
    wc_created_at = Column(DateTime, nullable=True)
    wc_modified_at = Column(DateTime, nullable=True)

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

    # Relationships
    wc_store = relationship("WooCommerceStore", back_populates="orders")
