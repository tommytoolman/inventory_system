"""
Per-tenant webhook endpoint configuration.

Allows tenants to receive event notifications (e.g. order.created,
sync.completed) at their own HTTPS endpoints.
"""

import uuid

from sqlalchemy import TIMESTAMP, Boolean, Column, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..database import Base


class TenantWebhook(Base):
    __tablename__ = "tenant_webhooks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    event_type = Column(String(100), nullable=False)
    webhook_url = Column(String(500), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"),
        nullable=False,
    )

    # Relationships
    tenant = relationship("Tenant", back_populates="webhooks")

    def __repr__(self):
        return f"<TenantWebhook {self.event_type} → {self.webhook_url[:40]}>"
