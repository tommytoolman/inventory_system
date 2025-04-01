"""
Shared enums and constants used across the application.
"""

from enum import Enum

class ProductStatus(str, Enum):
    """Product status values used in both models and schemas"""
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SOLD = "SOLD"
    ARCHIVED = "ARCHIVED"

class ProductCondition(str, Enum):
    """Product condition values used in both models and schemas"""
    NEW = "NEW"
    EXCELLENT = "EXCELLENT"
    VERY_GOOD = "VERYGOOD"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"

class ListingStatus(str, Enum):
    """Listing status values used in both models and schemas"""
    DRAFT = "draft"
    ACTIVE = "active"
    ENDED = "ended"
    SOLD = "sold"
    REMOVED = "removed"
    DELETED = "deleted"

class SyncStatus(str, Enum):
    """Sync status values used in both models and schemas"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    ERROR = "error"
    FAILED = "failed"