# app/models/listing_stats_history.py
"""
Listing Stats History Model

Stores daily snapshots of listing engagement metrics (views, watches)
for trend analysis and business intelligence across all platforms.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, TIMESTAMP, text, Index
from app.database import Base


class ListingStatsHistory(Base):
    """
    Model for tracking listing engagement metrics over time.

    One row per listing per snapshot (typically daily).
    Supports multiple platforms (Reverb, eBay, etc.)
    """
    __tablename__ = "listing_stats_history"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Platform identification
    platform = Column(String(50), nullable=False, index=True)  # 'reverb', 'ebay', etc.
    platform_listing_id = Column(String(100), nullable=False, index=True)  # External ID from platform
    product_id = Column(Integer, nullable=True, index=True)  # FK to products.id for easy navigation

    # Engagement metrics
    view_count = Column(Integer, nullable=True)
    watch_count = Column(Integer, nullable=True)

    # Context at time of snapshot
    price = Column(Float, nullable=True)  # Price at time of snapshot
    state = Column(String(50), nullable=True)  # Listing state (live, ended, etc.)

    # Timestamp
    recorded_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"),
        nullable=False,
        index=True,
    )

    # Composite index for efficient queries
    __table_args__ = (
        Index(
            'ix_listing_stats_history_platform_listing_date',
            'platform', 'platform_listing_id', 'recorded_at'
        ),
    )

    def __repr__(self):
        return (
            f"<ListingStatsHistory(platform={self.platform}, "
            f"listing_id={self.platform_listing_id}, "
            f"product_id={self.product_id}, "
            f"views={self.view_count}, watches={self.watch_count}, "
            f"recorded_at={self.recorded_at})>"
        )
