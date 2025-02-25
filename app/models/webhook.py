from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, JSON, Boolean
from app.database import Base

class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    
    id = Column(Integer, primary_key=True)
    event_type = Column(String)
    platform = Column(String)  # In this case will be 'website'
    payload = Column(JSON)
    processed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)