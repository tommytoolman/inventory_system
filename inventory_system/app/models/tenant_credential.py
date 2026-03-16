"""
Per-tenant API credentials for platform integrations.

Stores encrypted keys/secrets so each tenant can connect to their
own Reverb, eBay, Shopify, V&R, and WooCommerce accounts.
"""

import enum
import uuid

from sqlalchemy import TIMESTAMP, Boolean, Column, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import relationship

from ..database import Base


class CredentialType(str, enum.Enum):
    REVERB_API_KEY = "reverb_api_key"
    EBAY_AUTH = "ebay_auth"
    SHOPIFY_TOKEN = "shopify_token"
    VR_USERNAME = "vr_username"
    WOOCOMMERCE_KEY = "woocommerce_key"


class TenantCredential(Base):
    __tablename__ = "tenant_credentials"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    credential_type = Column(
        ENUM(CredentialType, name="credentialtype", create_type=True),
        nullable=False,
    )
    credential_key = Column(String(500), nullable=False)
    credential_secret = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

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
    tenant = relationship("Tenant", back_populates="credentials")

    def __repr__(self):
        return f"<TenantCredential {self.credential_type.value} tenant={self.tenant_id}>"
