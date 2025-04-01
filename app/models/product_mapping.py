# app/models/product_mapping.py
from sqlalchemy import Column, Integer, String, Float, ForeignKey, UniqueConstraint, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime

from app.database import Base

class ProductMapping(Base):
    __tablename__ = "product_mappings"
    
    id = Column(Integer, primary_key=True)
    
    # Primary product record
    master_product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    
    # Related product
    related_product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    
    # Metadata
    match_confidence = Column(Float)
    match_method = Column(String)  # 'manual', 'algorithm'
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    master_product = relationship("Product", foreign_keys=[master_product_id])
    related_product = relationship("Product", foreign_keys=[related_product_id])
    
    # Unique constraint to prevent duplicate mappings
    __table_args__ = (
        UniqueConstraint('master_product_id', 'related_product_id', name='unique_product_mapping'),
    )