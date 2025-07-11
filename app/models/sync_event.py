# app/models/sync_event.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.database import Base
from app.core.enums import PlatformName

class SyncEvent(Base):
    """
    Represents a single detected change during a platform sync.
    This table serves as a permanent audit log for all sync activities.
    """
    __tablename__ = "sync_events"

    id = Column(Integer, primary_key=True, index=True)
    
    # A unique ID to group all events from a single "sync all" run.
    sync_run_id = Column(UUID(as_uuid=True), index=True, nullable=False)

    # --- Source of the Event ---
    platform_name = Column(String, nullable=False, index=True)
    
    # --- Links to Local Data ---
    # Nullable for "rogue" listings found on a platform but not in our system yet.
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True, index=True)
    platform_common_id = Column(Integer, ForeignKey("platform_common.id"), nullable=True, index=True)
    external_id = Column(String, index=True, nullable=False)

    # --- Change Details ---
    change_type = Column(String, nullable=False, index=True) # e.g., 'status', 'price', 'inventory', 'new_listing'
    
    # JSONB column to store flexible change data, e.g., {"old": "active", "new": "sold"}
    change_data = Column(JSON, nullable=False)

    # --- Processing Status ---
    status = Column(String, default="pending", nullable=False, index=True) # pending, processed, ignored, error
    
    # --- Timestamps ---
    detected_at = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)
    
    # --- Metadata ---
    notes = Column(Text, nullable=True) # For storing error messages or reconciliation notes.

    def __repr__(self):
        return (f"<SyncEvent(id={self.id}, run_id={self.sync_run_id}, platform='{self.platform_name}', "
                f"product_id={self.product_id}, change='{self.change_type}', status='{self.status}')>")

