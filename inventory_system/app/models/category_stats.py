# app/models/category_stats.py
"""
Pre-computed category-level velocity and pricing statistics.
Refreshed periodically from reverb_historical_listings.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Date, Index
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base


class CategoryVelocityStats(Base):
    """
    Pre-computed velocity and pricing stats by category.

    These benchmarks are used to:
    - Compare current aged inventory against historical performance
    - Identify overpriced items
    - Predict time-to-sell
    - Set realistic pricing expectations
    """
    __tablename__ = "category_velocity_stats"

    id = Column(Integer, primary_key=True)
    category_root = Column(String, nullable=False, index=True)
    category_full = Column(String)  # Optional: full path for subcategory analysis

    # Time period for these stats
    period_start = Column(Date)
    period_end = Column(Date)
    period_type = Column(String, index=True)  # 'all_time', 'last_24m', 'last_12m', 'last_6m'

    # Volume metrics
    total_listed = Column(Integer, default=0)
    total_sold = Column(Integer, default=0)
    total_unsold = Column(Integer, default=0)  # Removed/expired without selling
    sell_through_rate = Column(Float)  # sold / listed as percentage

    # Velocity metrics (in days)
    avg_days_to_sell = Column(Float)
    median_days_to_sell = Column(Float)
    p25_days_to_sell = Column(Float)  # 25th percentile (fast sellers)
    p75_days_to_sell = Column(Float)  # 75th percentile (slow sellers)
    min_days_to_sell = Column(Integer)
    max_days_to_sell = Column(Integer)

    # Pricing metrics
    avg_list_price = Column(Float)  # Average initial listing price
    avg_sale_price = Column(Float)  # Average final sale price
    median_sale_price = Column(Float)
    min_sale_price = Column(Float)
    max_sale_price = Column(Float)

    # Price reduction patterns
    avg_price_reduction_pct = Column(Float)  # How much prices typically drop
    pct_items_reduced = Column(Float)  # % of items that had price drops
    avg_reductions_before_sale = Column(Float)  # Avg number of price drops

    # Engagement benchmarks (for sold items)
    avg_views_when_sold = Column(Float)
    avg_watches_when_sold = Column(Float)
    avg_offers_when_sold = Column(Float)
    avg_views_per_day = Column(Float)

    # Sample size for confidence
    sample_size = Column(Integer, default=0)

    # Computed at
    computed_at = Column(DateTime, default=datetime.utcnow)

    # Composite indexes
    __table_args__ = (
        Index('ix_category_velocity_period', 'category_root', 'period_type'),
    )

    def __repr__(self):
        return f"<CategoryVelocityStats {self.category_root} ({self.period_type})>"


class InventoryHealthSnapshot(Base):
    """
    Daily snapshot of inventory health metrics.

    Allows tracking improvement over time:
    - Is average age decreasing?
    - Is dead stock value reducing?
    - Are we improving platform coverage?
    """
    __tablename__ = "inventory_health_snapshots"

    id = Column(Integer, primary_key=True)
    snapshot_date = Column(Date, nullable=False, unique=True, index=True)

    # Overall metrics
    total_items = Column(Integer, default=0)
    total_value = Column(Float, default=0)

    # Age distribution (item counts)
    items_0_30d = Column(Integer, default=0)
    items_30_90d = Column(Integer, default=0)
    items_90_180d = Column(Integer, default=0)
    items_180_365d = Column(Integer, default=0)
    items_365_plus = Column(Integer, default=0)

    # Age distribution (values in GBP)
    value_0_30d = Column(Float, default=0)
    value_30_90d = Column(Float, default=0)
    value_90_180d = Column(Float, default=0)
    value_180_365d = Column(Float, default=0)
    value_365_plus = Column(Float, default=0)

    # Health indicators
    avg_age_days = Column(Float)
    median_age_days = Column(Float)

    # Problem inventory
    dead_stock_count = Column(Integer, default=0)  # 0 views, 0 watches, 0 offers
    dead_stock_value = Column(Float, default=0)
    stale_count = Column(Integer, default=0)  # Listed 90+ days, < 5 watches
    stale_value = Column(Float, default=0)

    # Platform coverage
    single_platform_count = Column(Integer, default=0)
    two_platform_count = Column(Integer, default=0)
    three_plus_platform_count = Column(Integer, default=0)

    # Engagement summary
    total_views = Column(Integer, default=0)
    total_watches = Column(Integer, default=0)
    avg_views_per_item = Column(Float)
    avg_watches_per_item = Column(Float)

    # By category breakdown (JSONB for flexibility)
    category_breakdown = Column(JSONB)
    # Structure: {
    #   "Electric Guitars": {"count": 150, "value": 450000, "avg_age": 120, "dead_stock": 12},
    #   "Amps": {"count": 80, "value": 120000, "avg_age": 95, "dead_stock": 5},
    #   ...
    # }

    # Computed at
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<InventoryHealthSnapshot {self.snapshot_date}>"
