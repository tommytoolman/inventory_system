import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base


class SyncErrorRecord(Base):
    __tablename__ = "sync_errors"

    id = Column(String(12), primary_key=True, default=lambda: str(uuid.uuid4())[:8].upper())
    product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True)
    platform = Column(String(50), nullable=False, index=True)
    operation = Column(String(20), nullable=False)
    error_message = Column(Text, nullable=False)
    error_type = Column(String(100), nullable=False)
    stack_trace = Column(Text, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    extra_context = Column(JSONB, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    resolved = Column(Boolean, nullable=False, default=False)
    resolution_notes = Column(Text, nullable=True)
