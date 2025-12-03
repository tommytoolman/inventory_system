"""
Shared enums and constants used across the application.
"""

from enum import Enum

class PlatformName(str, Enum):
    REVERB = "REVERB"
    SHOPIFY = "SHOPIFY"
    EBAY = "EBAY"
    VR = "VR"
    
    @property
    def slug(self):
        # self.value will be "EBAY", "REVERB", "VR", "SHOPIFY"
        # .lower() makes them "ebay", "reverb", "vr", "shopify"
        # The replace calls are good practice for more complex names,
        # though for these simple names, only .lower() is strictly needed.
        return self.value.lower().replace('& ', 'and').replace(' ', '').replace('-', '')
    

class ProductStatus(str, Enum):
    """Product status values used in both models and schemas"""
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SOLD = "SOLD"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"

class ProductCondition(str, Enum):
    """Product condition values used in both models and schemas"""
    NEW = "NEW"
    EXCELLENT = "EXCELLENT"
    VERYGOOD = "VERYGOOD"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"


class Handedness(str, Enum):
    RIGHT = "RIGHT"
    LEFT = "LEFT"
    AMBIDEXTROUS = "AMBIDEXTROUS"
    UNSPECIFIED = "UNSPECIFIED"

class ManufacturingCountry(str, Enum):
    UNITED_KINGDOM = "GB"
    UNITED_STATES = "US"
    CANADA = "CA"
    JAPAN = "JP"
    GERMANY = "DE"
    FRANCE = "FR"
    ITALY = "IT"
    SPAIN = "ES"
    SWEDEN = "SE"
    NORWAY = "NO"
    DENMARK = "DK"
    MEXICO = "MX"
    INDONESIA = "ID"
    CHINA = "CN"
    KOREA = "KR"
    TAIWAN = "TW"
    AUSTRALIA = "AU"
    NEW_ZEALAND = "NZ"
    BRAZIL = "BR"
    CZECH_REPUBLIC = "CZ"
    RUSSIA = "RU"
    VIETNAM = "VN"
    OTHER = "OTHER"


class InventoryLocation(str, Enum):
    HANKS = "HANKS"
    DONCASTER = "DONCASTER"
    UNSPECIFIED = "UNSPECIFIED"


class Storefront(str, Enum):
    HANKS = "HANKS"
    LONDON_VINTAGE_GUITARS = "LONDON VINTAGE GUITARS"
    UNSPECIFIED = "UNSPECIFIED"


class CaseStatus(str, Enum):
    NONE = "NONE"
    ORIGINAL = "ORIGINAL"
    PERIOD_CORRECT = "PERIOD_CORRECT"
    AFTERMARKET = "AFTERMARKET"
    GIG_BAG = "GIG_BAG"
    FLIGHT_CASE = "FLIGHT_CASE"
    UNSPECIFIED = "UNSPECIFIED"


class ListingStatus(str, Enum):
    """Listing status values used in both models and schemas"""
    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "unsold"
    ENDED = "ended"
    SOLD = "sold"
    REMOVED = "removed"
    DELETED = "deleted"
    UNMATCHED = "unmatched"

class SyncStatus(str, Enum):
    """Consolidated sync status values used across the application."""
    PENDING = "pending"          # Sync action initiated or scheduled
    IN_PROGRESS = "in_progress"  # Sync action currently running
    SYNCED = "synced"            # Local data matches the platform (equivalent to SUCCESS)
    OUT_OF_SYNC = "out_of_sync"  # Local data is known not to match the platform
    ERROR = "error"              # An error occurred during the sync attempt (e.g., API error)
    NEEDS_REVIEW = "needs_review"  # For rogue listings needing manual attention
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
