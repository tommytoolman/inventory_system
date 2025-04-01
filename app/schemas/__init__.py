"""
Schema exports.
"""
from .base import BaseSchema, TimestampedSchema
from .product import ProductCreate, ProductUpdate, ProductRead

# Platform schemas
from .platform.common import (
    PlatformListingBase,
    PlatformListingCreate,
    PlatformListingUpdate,
    PlatformListingRead
)

from .platform.ebay import (
    EbayListingCreate,
    EbayListingUpdate,
    EbayListingRead,
    EbayListingStatus
)
