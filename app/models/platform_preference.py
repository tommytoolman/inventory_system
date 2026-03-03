# app/models/platform_preference.py
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.database import Base


class PlatformPreference(Base):
    __tablename__ = "platform_preferences"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False, index=True)
    show_ebay = Column(Boolean, default=True, nullable=False)
    show_reverb = Column(Boolean, default=True, nullable=False)
    show_shopify = Column(Boolean, default=True, nullable=False)
    show_vintage_rare = Column(Boolean, default=True, nullable=False)
    show_woocommerce = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Map between platform slugs used in the codebase and column names
    PLATFORM_COLUMN_MAP = {
        "ebay": "show_ebay",
        "reverb": "show_reverb",
        "shopify": "show_shopify",
        "vr": "show_vintage_rare",
        "woocommerce": "show_woocommerce",
    }

    def get_visible_platforms(self) -> list:
        """Return list of platform slugs the user wants to see."""
        visible = []
        for slug, col in self.PLATFORM_COLUMN_MAP.items():
            if getattr(self, col, True):
                visible.append(slug)
        return visible

    def to_dict(self) -> dict:
        """Return preferences as a dict for template rendering."""
        return {col: getattr(self, col, True) for col in self.PLATFORM_COLUMN_MAP.values()}
