# app/models/category_mapping.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, text, TIMESTAMP
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

UTC_NOW = text("now() at time zone 'utc'")

from app.database import Base

class CategoryMapping(Base):
    """Model for category mappings between platforms"""
    __tablename__ = "category_mappings"
    
    id = Column(Integer, primary_key=True)
    source_platform = Column(String, nullable=False)
    source_id = Column(String, nullable=False)
    source_name = Column(String, nullable=False)
    target_platform = Column(String, nullable=False)
    target_id = Column(String, nullable=False)
    target_subcategory_id = Column(String)
    target_tertiary_id = Column(String)
    
    # created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=UTC_NOW)
    # updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=UTC_NOW)
    
    created_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"), # Use standard PG function via text()
        nullable=False
    )
    updated_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"), # Use standard PG function via text()
        onupdate=text("timezone('utc', now())"),      # Use standard PG function via text() for ON UPDATE
        nullable=False
    )