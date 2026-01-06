# app/models/reverb_historical.py
"""
Historical Reverb listings - items that have sold or been removed.
Used for velocity analysis, pricing benchmarks, and category insights.
NOT part of active inventory (products/reverb_listings tables).
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Date, Index
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base


class ReverbHistoricalListing(Base):
    """
    Historical Reverb listings for analytics and benchmarking.

    This table stores ~5000 historical listings that are NOT in active inventory,
    providing velocity and pricing benchmarks for inventory optimization.
    """
    __tablename__ = "reverb_historical_listings"

    id = Column(Integer, primary_key=True)
    reverb_listing_id = Column(String, unique=True, nullable=False, index=True)

    # Core product info
    title = Column(String)
    sku = Column(String, index=True)
    brand = Column(String, index=True)
    model = Column(String)
    category_full = Column(String, index=True)  # Full Reverb category path
    category_root = Column(String, index=True)  # Top-level: "Electric Guitars", "Amps", etc.
    condition = Column(String)
    year = Column(String)  # Year of manufacture if available
    finish = Column(String)

    # Pricing
    original_price = Column(Float)  # Initial listing price (if available)
    final_price = Column(Float)  # Price when sold/ended
    currency = Column(String, default="GBP")

    # Dates
    created_at = Column(DateTime)  # When first listed on Reverb
    sold_at = Column(DateTime, index=True)  # When sold (NULL if not sold)
    ended_at = Column(DateTime)  # When listing ended (sold, removed, expired)

    # Outcome
    outcome = Column(String, index=True)  # 'sold', 'removed', 'expired', 'relisted'
    days_listed = Column(Integer)  # Total days the listing was active
    days_to_sell = Column(Integer)  # Calculated: sold_at - created_at (NULL if not sold)

    # Engagement (final snapshot)
    view_count = Column(Integer, default=0)
    watch_count = Column(Integer, default=0)
    offer_count = Column(Integer, default=0)

    # Price movement tracking
    price_drops = Column(Integer, default=0)  # Number of price reductions
    total_price_reduction = Column(Float)  # original_price - final_price
    price_reduction_pct = Column(Float)  # Percentage dropped

    # Images
    primary_image = Column(String)
    image_count = Column(Integer, default=0)

    # Seller info (for multi-shop support)
    shop_id = Column(String, index=True)
    shop_name = Column(String)

    # Raw data for future analysis
    raw_data = Column(JSONB)  # Full API response

    # Metadata
    imported_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Composite indexes for common queries
    __table_args__ = (
        Index('ix_reverb_historical_category_outcome', 'category_root', 'outcome'),
        Index('ix_reverb_historical_sold_date', 'sold_at', 'category_root'),
        Index('ix_reverb_historical_brand_category', 'brand', 'category_root'),
    )

    def __repr__(self):
        return f"<ReverbHistoricalListing {self.reverb_listing_id}: {self.title}>"
