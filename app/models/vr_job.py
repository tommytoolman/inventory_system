from datetime import datetime
from enum import Enum

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.database import Base


class VRJobStatus(str, Enum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED_PENDING_ID = "completed_pending_id"  # Listing created, V&R ID not yet resolved
    COMPLETED = "completed"
    FAILED = "failed"


class VRJob(Base):
    __tablename__ = "vr_jobs"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    payload = Column(JSONB(astext_type=Text()), nullable=False)
    status = Column(String(32), nullable=False, default=VRJobStatus.QUEUED.value)
    error_message = Column(Text, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = relationship("Product", back_populates="vr_jobs")
