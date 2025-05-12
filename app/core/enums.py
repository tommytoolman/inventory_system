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
    VERY_GOOD = "VERY_GOOD"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"

class ListingStatus(str, Enum):
    """Listing status values used in both models and schemas"""
    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "unsold"
    ENDED = "ended"
    SOLD = "sold"
    REMOVED = "removed"
    DELETED = "deleted"

class SyncStatus(str, Enum):
    """Consolidated sync status values used across the application."""
    PENDING = "pending"          # Sync action initiated or scheduled
    IN_PROGRESS = "in_progress"  # Sync action currently running
    SYNCED = "synced"            # Local data matches the platform (equivalent to SUCCESS)
    OUT_OF_SYNC = "out_of_sync"  # Local data is known not to match the platform
    ERROR = "error"              # An error occurred during the sync attempt (e.g., API error)
    # FAILED = "failed"          # Removed for now, assuming ERROR/OUT_OF_SYNC cover needs
    
class EbayListingStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ENDED = "ended"
    SCHEDULED = "scheduled"
    PENDING = "pending"
    
class EbayListingFormat(str, Enum):
    BUY_IT_NOW = "Buy it Now"
    AUCTION = "Auction"
    AUCTION_BIN = "Auction with Buy it Now"
    
class ShipmentStatus(str,Enum):
    """Shipment status enum"""
    CREATED = "created"
    LABEL_CREATED = "label_created"
    PICKED_UP = "picked_up"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    EXCEPTION = "exception"
    CANCELLED = "cancelled"