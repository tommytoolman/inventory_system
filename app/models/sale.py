# app/models/sale.py

from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Float, ForeignKey, text, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from ..database import Base


class Sale(Base):
    """Represents a platform sale/order event."""

    __tablename__ = "sales"

    id = Column(Integer, primary_key=True)

    created_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"),
        nullable=False,
    )

    sale_date = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"),
        nullable=False,
    )

    product_id = Column(Integer, ForeignKey("products.id"), index=True, nullable=False)
    platform_listing_id = Column(Integer, ForeignKey("platform_common.id"), index=True, nullable=False)

    platform_name = Column(String, nullable=False)
    platform_external_id = Column(String, nullable=False)
    status = Column(String, nullable=False)

    sale_price = Column(Float, nullable=True)
    original_list_price = Column(Float, nullable=True)
    platform_fees = Column(Float, nullable=True)
    shipping_cost = Column(Float, nullable=True)
    net_amount = Column(Float, nullable=True)
    days_to_sell = Column(Integer, nullable=True)

    payment_method = Column(String, nullable=True)
    shipping_method = Column(String, nullable=True)
    order_reference = Column(String, nullable=True)

    buyer_name = Column(String, nullable=True)
    buyer_email = Column(String, nullable=True)
    buyer_phone = Column(String, nullable=True)
    buyer_address = Column(JSONB, nullable=True)
    buyer_location = Column(String, nullable=True)

    platform_data = Column(JSONB, nullable=True, default=dict)

    product = relationship("Product", back_populates="sales")
    platform_listing = relationship("PlatformCommon", back_populates="sale")
    shipments = relationship("Shipment", back_populates="sale")

    def __repr__(self) -> str:
        return (
            f"<Sale id={self.id} product={self.product_id} platform={self.platform_name} "
            f"external_id={self.platform_external_id} status={self.status}>"
        )
