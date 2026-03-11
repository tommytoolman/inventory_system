from sqlalchemy import Column, Integer, String, Text, UniqueConstraint, DateTime
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from app.database import Base
from app.core.enums import ProductCondition


class PlatformConditionMapping(Base):
    """
    Represents the mapping between our internal ProductCondition values and
    platform-specific identifiers (e.g., Reverb UUIDs, eBay Condition IDs).
    """

    __tablename__ = "platform_condition_mappings"
    __table_args__ = (
        UniqueConstraint(
            "platform_name",
            "condition",
            "category_scope",
            name="uq_platform_condition_scope",
        ),
    )

    id = Column(Integer, primary_key=True)
    platform_name = Column(String(32), nullable=False, index=True)
    condition = Column(
        PGEnum(ProductCondition, name="productcondition", create_type=False),
        nullable=False,
        index=True,
    )
    platform_condition_id = Column(String(128), nullable=False)
    display_name = Column(String(128), nullable=True)
    description = Column(Text, nullable=True)
    category_scope = Column(String(64), nullable=False, server_default="default")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<PlatformConditionMapping(platform={self.platform_name}, "
            f"condition={self.condition}, scope={self.category_scope}, "
            f"platform_condition_id={self.platform_condition_id})>"
        )
