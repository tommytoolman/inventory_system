"""
Sync Statistics Model

Tracks cumulative statistics for sync operations across all platforms.
"""

from sqlalchemy import Column, Integer, DateTime, String, JSON, BigInteger
from sqlalchemy.sql import func
from app.database import Base


class SyncStats(Base):
    """
    Tracks statistics for sync operations.
    
    This table maintains running totals and per-sync-run breakdowns of:
    - Events processed
    - Sales detected
    - Listings created/updated/removed
    - Errors encountered
    - Processing times
    """
    __tablename__ = "sync_stats"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Timestamp for this stats entry
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Optional sync_run_id if this is for a specific sync run
    sync_run_id = Column(String, nullable=True, index=True)
    
    # Platform-specific stats (null for aggregate stats)
    platform = Column(String, nullable=True, index=True)
    
    # Cumulative totals (updated incrementally)
    total_events_processed = Column(BigInteger, default=0)
    total_sales = Column(BigInteger, default=0)
    total_listings_created = Column(BigInteger, default=0)
    total_listings_updated = Column(BigInteger, default=0)
    total_listings_removed = Column(BigInteger, default=0)
    total_price_changes = Column(BigInteger, default=0)
    total_errors = Column(BigInteger, default=0)
    total_partial_syncs = Column(BigInteger, default=0)
    total_successful_syncs = Column(BigInteger, default=0)
    
    # Per-run stats (for this specific sync operation)
    run_events_processed = Column(Integer, default=0)
    run_sales = Column(Integer, default=0)
    run_listings_created = Column(Integer, default=0)
    run_listings_updated = Column(Integer, default=0)
    run_listings_removed = Column(Integer, default=0)
    run_price_changes = Column(Integer, default=0)
    run_errors = Column(Integer, default=0)
    run_duration_seconds = Column(Integer, nullable=True)
    
    # Additional metadata
    metadata_json = Column(JSON, nullable=True)  # For storing extra details
    
    def __repr__(self):
        return f"<SyncStats(id={self.id}, platform={self.platform}, events={self.total_events_processed})>"