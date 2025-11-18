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


class ReverbOrder(Base):
    __tablename__ = "reverb_orders"

    id = Column(Integer, primary_key=True, index=True)
    order_uuid = Column(String, nullable=False)
    order_number = Column(String)
    order_bundle_id = Column(String)
    reverb_listing_id = Column(String)
    title = Column(String)
    shop_name = Column(String)
    sku = Column(String)
    status = Column(String)
    order_type = Column(String)
    order_source = Column(String)
    shipment_status = Column(String)
    shipping_method = Column(String)
    payment_method = Column(String)
    local_pickup = Column(Boolean)
    needs_feedback_for_buyer = Column(Boolean)
    needs_feedback_for_seller = Column(Boolean)
    shipping_taxed = Column(Boolean)
    tax_responsible_party = Column(String)
    tax_rate = Column(Numeric)
    quantity = Column(Integer)
    buyer_id = Column(Integer)
    buyer_name = Column(String)
    buyer_first_name = Column(String)
    buyer_last_name = Column(String)
    buyer_email = Column(String)
    shipping_name = Column(String)
    shipping_phone = Column(String)
    shipping_city = Column(String)
    shipping_region = Column(String)
    shipping_postal_code = Column(String)
    shipping_country_code = Column(String)
    created_at = Column(DateTime)
    paid_at = Column(DateTime)
    updated_at = Column(DateTime)
    amount_product = Column(Numeric)
    amount_product_currency = Column(String)
    amount_product_subtotal = Column(Numeric)
    amount_product_subtotal_currency = Column(String)
    shipping_amount = Column(Numeric)
    shipping_currency = Column(String)
    tax_amount = Column(Numeric)
    tax_currency = Column(String)
    total_amount = Column(Numeric)
    total_currency = Column(String)
    direct_checkout_fee_amount = Column(Numeric)
    direct_checkout_fee_currency = Column(String)
    direct_checkout_payout_amount = Column(Numeric)
    direct_checkout_payout_currency = Column(String)
    tax_on_fees_amount = Column(Numeric)
    tax_on_fees_currency = Column(String)
    shipping_address = Column(JSON)
    order_notes = Column(JSON)
    photos = Column(JSON)
    links = Column(JSON)
    presentment_amounts = Column(JSON)
    raw_payload = Column(JSON, nullable=False, server_default=text("'{}'::jsonb"))
    product_id = Column(Integer)
    platform_listing_id = Column(Integer)
    created_row_at = Column(DateTime, nullable=False, server_default=text("timezone('utc', now())"))
    updated_row_at = Column(DateTime, nullable=False, server_default=text("timezone('utc', now())"))
