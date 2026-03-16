"""
Per-tenant resource usage tracking.

Records sync events, orders, API calls, and storage consumption
per billing period for metering and billing purposes.
"""

import uuid

from sqlalchemy import TIMESTAMP, BigInteger, Column, Date, ForeignKey, Integer, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..database import Base


class TenantUsage(Base):
    __tablename__ = "tenant_usage"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)

    sync_events_count = Column(Integer, default=0, nullable=False)
    orders_count = Column(Integer, default=0, nullable=False)
    api_calls_count = Column(Integer, default=0, nullable=False)
    storage_bytes = Column(BigInteger, default=0, nullable=False)

    created_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"),
        nullable=False,
    )

    # Relationships
    tenant = relationship("Tenant", back_populates="usage_records")

    def __repr__(self):
        return f"<TenantUsage tenant={self.tenant_id} {self.period_start}–{self.period_end}>"
