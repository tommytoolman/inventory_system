from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    DateTime,
    Boolean,
    JSON,
    ForeignKey,
    text,
)
from app.database import Base


class ShopifyOrder(Base):
    __tablename__ = "shopify_orders"

    id = Column(Integer, primary_key=True, index=True)
    # Shopify order identifiers
    shopify_order_id = Column(String, nullable=False, unique=True)  # gid://shopify/Order/...
    order_name = Column(String)  # #1001, #1002, etc.

    # Order status
    financial_status = Column(String)  # PAID, PENDING, REFUNDED, etc.
    fulfillment_status = Column(String)  # FULFILLED, UNFULFILLED, PARTIAL

    # Dates
    created_at = Column(DateTime)
    paid_at = Column(DateTime)
    fulfilled_at = Column(DateTime)

    # Financial details
    total_amount = Column(Numeric)
    total_currency = Column(String)
    subtotal_amount = Column(Numeric)
    subtotal_currency = Column(String)
    shipping_amount = Column(Numeric)
    shipping_currency = Column(String)
    tax_amount = Column(Numeric)
    tax_currency = Column(String)

    # Customer details
    customer_id = Column(String)
    customer_first_name = Column(String)
    customer_last_name = Column(String)
    customer_email = Column(String)
    customer_phone = Column(String)

    # Shipping address
    shipping_name = Column(String)
    shipping_address1 = Column(String)
    shipping_address2 = Column(String)
    shipping_city = Column(String)
    shipping_province = Column(String)
    shipping_province_code = Column(String)
    shipping_country = Column(String)
    shipping_country_code = Column(String)
    shipping_zip = Column(String)
    shipping_phone = Column(String)
    shipping_company = Column(String)

    # Billing address (stored as JSON for simplicity)
    billing_address = Column(JSON)

    # Fulfillment/tracking
    tracking_number = Column(String)
    tracking_company = Column(String)
    tracking_url = Column(String)
    fulfillments = Column(JSON)  # Full fulfillment data

    # Line items - primary item for single-item orders
    primary_sku = Column(String)
    primary_title = Column(String)
    primary_quantity = Column(Integer)
    primary_price = Column(Numeric)
    primary_price_currency = Column(String)
    line_items = Column(JSON)  # Full line items array

    # Raw data and linkage
    raw_payload = Column(JSON, nullable=False, server_default=text("'{}'::jsonb"))
    product_id = Column(Integer)  # Link to products table
    platform_listing_id = Column(Integer)  # Link to platform_common

    # Row timestamps
    created_row_at = Column(DateTime, nullable=False, server_default=text("timezone('utc', now())"))
    updated_row_at = Column(DateTime, nullable=False, server_default=text("timezone('utc', now())"))

    # Sale processing for inventory management
    sale_processed = Column(Boolean, nullable=False, server_default=text("false"))
    sale_processed_at = Column(DateTime, nullable=True)
