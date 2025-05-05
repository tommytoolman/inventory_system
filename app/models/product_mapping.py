# app/models/product_mapping.py
from sqlalchemy import Column, Integer, String, Float, ForeignKey, UniqueConstraint, DateTime, text, TIMESTAMP
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from app.database import Base

UTC_NOW = text("now() AT TIME ZONE 'utc'")

class ProductMapping(Base):
    """
    Maps potentially duplicate Product records identified during initial
    inventory synchronization from multiple platforms. Links related product
    entries to a designated master product entry, recording the match method
    and confidence. I THINK ... not currently imported so it might be redundant.
    """
    __tablename__ = "product_mappings"
    
    id = Column(Integer, primary_key=True)
    
    # Primary product record
    master_product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    
    # Related product
    related_product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    
    # Metadata
    match_confidence = Column(Float)
    match_method = Column(String)  # 'manual', 'algorithm'
    # created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=UTC_NOW)
    
    created_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"), # Use standard PG function via text()
        nullable=False
    )
    # Relationships
    master_product = relationship("Product", foreign_keys=[master_product_id])
    related_product = relationship("Product", foreign_keys=[related_product_id])
    
    # Unique constraint to prevent duplicate mappings
    __table_args__ = (
        UniqueConstraint('master_product_id', 'related_product_id', name='unique_product_mapping'),
    )