"""
Schema exports for the application.
"""

# Base schemas
from .base import BaseSchema, TimestampedSchema

# Product schemas
from .product import ProductBase, ProductCreate, ProductUpdate, ProductRead

# Common Platform schemas
from .platform.common import (
    PlatformListingBase,
    PlatformListingCreate,
    PlatformListingUpdate,
    PlatformListingRead
)

# Platform-Specific Schemas
from .platform.ebay import (
    EbayListingBase,
    EbayListingCreate,
    EbayListingUpdate,
    EbayListingRead,
    EbayListingStatusInfo
)
from .platform.reverb import (
    ReverbListingBase,
    ReverbListingCreateDTO, # Keep DTO if you decide to use it consistently
    ReverbListingUpdateDTO, # Or remove DTO suffix consistently
    ReverbListingReadDTO,
    ReverbListingStatusDTO,
    ReverbCategoryDTO,       # Only if used
    ReverbConditionDTO       # Only if used
)
from .platform.vr import (
    VRListingCreateDTO,     # Decide on DTO suffix
    VRListingStatusDTO
)
from .platform.website import (
    WebsiteListingCreateDTO, # Decide on DTO suffix
    WebsiteListingStatusDTO
)

# Combined Platform Schemas (if kept)
from .platform.combined import (
    MultiPlatformListingCreateDTO, # Decide on DTO suffix
    PlatformSyncStatusDTO
)
