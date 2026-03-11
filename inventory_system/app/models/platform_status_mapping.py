# app/models/platform_status_mapping.py
from sqlalchemy import Column, Integer, String, Text, DateTime, UniqueConstraint, CheckConstraint, text
from app.database import Base

class PlatformStatusMapping(Base):
    """
    Maps platform-specific status strings (e.g., 'Completed', 'ended-with-sales')
    to a canonical central status (e.g., 'sold', 'active').
    This model reflects the existing database table schema.
    """
    __tablename__ = 'platform_status_mappings'

    id = Column(Integer, primary_key=True)
    platform_name = Column(String(50), nullable=False)
    platform_status = Column(String(100), nullable=False) # The status string from the platform's API/CSV
    central_status = Column(String(20), nullable=False) # Your system's canonical status
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=text('CURRENT_TIMESTAMP'))
    updated_at = Column(DateTime, server_default=text('CURRENT_TIMESTAMP'), onupdate=text('CURRENT_TIMESTAMP'))

    __table_args__ = (
        UniqueConstraint('platform_name', 'platform_status', name='platform_status_mappings_platform_name_platform_status_key'),
        CheckConstraint("central_status IN ('LIVE', 'SOLD', 'DRAFT')", name='platform_status_mappings_central_status_check')
    )

    def __repr__(self):
        return f"<PlatformStatusMapping(platform='{self.platform_name}', platform_status='{self.platform_status}', central_status='{self.central_status}')>"