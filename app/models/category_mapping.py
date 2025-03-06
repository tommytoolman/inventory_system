# app/models/category_mapping.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)