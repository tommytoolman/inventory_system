"""
Tenant-User association (many-to-many).

Links users to tenants with a role that controls access level.
"""

import enum
import uuid

from sqlalchemy import TIMESTAMP, Column, ForeignKey, Integer, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import relationship

from ..database import Base


class TenantRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class TenantUser(Base):
    __tablename__ = "tenant_users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    role = Column(
        ENUM(TenantRole, name="tenantrole", create_type=True),
        nullable=False,
        server_default="viewer",
    )

    created_at = Column(
        TIMESTAMP(timezone=False),
        server_default=text("timezone('utc', now())"),
        nullable=False,
    )

    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_tenant_user"),)

    # Relationships
    tenant = relationship("Tenant", back_populates="tenant_users")

    def __repr__(self):
        return f"<TenantUser tenant={self.tenant_id} user={self.user_id} role={self.role.value}>"
