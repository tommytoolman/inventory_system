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


class EbayOrder(Base):
    __tablename__ = "ebay_orders"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(String, nullable=False)
    extended_order_id = Column(String)
    order_status = Column(String)
    checkout_status = Column(JSON)
    created_time = Column(DateTime)
    paid_time = Column(DateTime)
    shipped_time = Column(DateTime)
    buyer_user_id = Column(String)
    seller_user_id = Column(String)
    amount_paid = Column(Numeric)
    amount_paid_currency = Column(String)
    total_amount = Column(Numeric)
    total_currency = Column(String)
    shipping_cost = Column(Numeric)
    shipping_currency = Column(String)
    subtotal_amount = Column(Numeric)
    subtotal_currency = Column(String)
    item_id = Column(String)
    order_line_item_id = Column(String)
    transaction_id = Column(String)
    inventory_reservation_id = Column(String)
    sales_record_number = Column(String)
    primary_sku = Column(String)
    quantity_purchased = Column(Integer)
    transaction_price = Column(Numeric)
    transaction_currency = Column(String)
    tracking_number = Column(String)
    tracking_carrier = Column(String)
    shipping_service = Column(String)
    shipping_details = Column(JSON)
    shipping_address = Column(JSON)
    shipping_name = Column(String)
    shipping_country = Column(String)
    shipping_city = Column(String)
    shipping_state = Column(String)
    shipping_postal_code = Column(String)
    transactions = Column(JSON)
    monetary_details = Column(JSON)
    raw_payload = Column(JSON, nullable=False, server_default=text("'{}'::jsonb"))
    product_id = Column(Integer)
    platform_listing_id = Column(Integer)
    created_at = Column(DateTime, nullable=False, server_default=text("timezone('utc', now())"))
    updated_at = Column(DateTime, nullable=False, server_default=text("timezone('utc', now())"))
