from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.sql import func

from app.database import Base


class Job(Base):
    """
    Generic background job record.
    """

    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)
    job_type = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="pending", index=True)  # pending, running, success, error
    payload = Column(JSON, nullable=True)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Job(id={self.id}, type={self.job_type}, status={self.status})>"
