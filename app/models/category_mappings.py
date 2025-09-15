"""
SQLAlchemy models for normalized category mappings
"""
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Numeric, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class ReverbCategory(Base):
    __tablename__ = "reverb_categories"

    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False, index=True)
    full_path = Column(String)
    parent_uuid = Column(String)
    item_count = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    ebay_mappings = relationship("EbayCategoryMapping", back_populates="reverb_category", cascade="all, delete-orphan")
    shopify_mappings = relationship("ShopifyCategoryMapping", back_populates="reverb_category", cascade="all, delete-orphan")
    vr_mappings = relationship("VRCategoryMapping", back_populates="reverb_category", cascade="all, delete-orphan")


class EbayCategoryMapping(Base):
    __tablename__ = "ebay_category_mappings"

    id = Column(Integer, primary_key=True, index=True)
    reverb_category_id = Column(Integer, ForeignKey("reverb_categories.id", ondelete="CASCADE"), nullable=False, index=True)
    ebay_category_id = Column(String, nullable=False, index=True)
    ebay_category_name = Column(String, nullable=False)
    confidence_score = Column(Numeric(3, 2), default=1.0)
    is_verified = Column(Boolean, default=False)
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    reverb_category = relationship("ReverbCategory", back_populates="ebay_mappings")


class ShopifyCategoryMapping(Base):
    __tablename__ = "shopify_category_mappings"

    id = Column(Integer, primary_key=True, index=True)
    reverb_category_id = Column(Integer, ForeignKey("reverb_categories.id", ondelete="CASCADE"), nullable=False, index=True)
    shopify_gid = Column(String, nullable=False, index=True)
    shopify_category_name = Column(String, nullable=False)
    merchant_type = Column(String)
    confidence_score = Column(Numeric(3, 2), default=1.0)
    is_verified = Column(Boolean, default=False)
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    reverb_category = relationship("ReverbCategory", back_populates="shopify_mappings")


class VRCategoryMapping(Base):
    __tablename__ = "vr_category_mappings"

    id = Column(Integer, primary_key=True, index=True)
    reverb_category_id = Column(Integer, ForeignKey("reverb_categories.id", ondelete="CASCADE"), nullable=False, index=True)
    vr_category_id = Column(String, nullable=False, index=True)
    vr_category_name = Column(String)
    vr_subcategory_id = Column(String)
    vr_subcategory_name = Column(String)
    vr_sub_subcategory_id = Column(String)
    vr_sub_subcategory_name = Column(String)
    vr_sub_sub_subcategory_id = Column(String)
    vr_sub_sub_subcategory_name = Column(String)
    confidence_score = Column(Numeric(3, 2), default=1.0)
    is_verified = Column(Boolean, default=False)
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    reverb_category = relationship("ReverbCategory", back_populates="vr_mappings")