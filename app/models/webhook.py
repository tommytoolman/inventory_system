# Currently not being used. This was for the old website but now moving to Shopify. May not be required.

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, JSON, Boolean, text, TIMESTAMP
from app.database import Base

UTC_NOW = text("now() AT TIME ZONE 'utc'")

class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    
    id = Column(Integer, primary_key=True)
    event_type = Column(String)
    platform = Column(String)  # In this case will be 'website'
    payload = Column(JSON)
    processed = Column(Boolean, default=False)
    # created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=UTC_NOW)
    processed_at = Column(DateTime, nullable=True)
    
    
    created_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"), # Use standard PG function via text()
        nullable=False
    )