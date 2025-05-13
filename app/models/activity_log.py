# app/models/activity_log.py
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB
from app.database import Base

class ActivityLog(Base):
    """
    Records all significant activities in the system for auditing and monitoring.
    
    This includes:
    - Product updates (create, update, delete)
    - Platform syncs (ebay, reverb, vr, website)
    - Sales and status changes
    - Error events
    """
    __tablename__ = "activity_log"
    
    id = Column(Integer, primary_key=True)
    action = Column(String(50), nullable=False, index=True)  # 'create', 'update', 'delete', 'sync', 'sale'
    entity_type = Column(String(50), nullable=False, index=True)  # 'product', 'platform_listing', etc.
    entity_id = Column(String(100), nullable=False, index=True)  # ID of the affected entity
    platform = Column(String(50), nullable=True, index=True)  # Platform name if applicable
    
    # Store additional details in JSON format
    details = Column(JSONB, nullable=True)  
    
    # Removed foreign key: user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    # Simple user_id without foreign key constraint
    user_id = Column(Integer, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    
    def __repr__(self):
        return f"<ActivityLog {self.action} {self.entity_type} {self.entity_id}>"