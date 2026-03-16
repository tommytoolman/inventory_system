"""
Tenant model — core organisational entity for multi-tenancy.

Each tenant represents a retailer (e.g. Hanks Music) with their own
products, listings, orders, and platform credentials.
"""

import enum
import uuid

from sqlalchemy import TIMESTAMP, Column, String, text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import relationship

from ..database import Base


class TenantStatus(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    status = Column(
        ENUM(TenantStatus, name="tenantstatus", create_type=True),
        nullable=False,
        server_default="active",
    )

    # Python attribute named metadata_ to avoid collision with SQLAlchemy's
    # Base.metadata; the actual DB column is called "metadata".
    metadata_ = Column("metadata", JSONB, nullable=True, server_default=text("'{}'::jsonb"))

    created_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"),
        nullable=False,
    )
    updated_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"),
        onupdate=text("timezone('utc', now())"),
        nullable=False,
    )

    # Relationships
    credentials = relationship("TenantCredential", back_populates="tenant", cascade="all, delete-orphan")
    tenant_users = relationship("TenantUser", back_populates="tenant", cascade="all, delete-orphan")
    webhooks = relationship("TenantWebhook", back_populates="tenant", cascade="all, delete-orphan")
    usage_records = relationship("TenantUsage", back_populates="tenant", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Tenant {self.slug} ({self.status.value})>"
