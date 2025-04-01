from .product import Product, ProductStatus, ProductCondition
from .platform_common import PlatformCommon, ListingStatus, SyncStatus
from .ebay import EbayListing
from .reverb import ReverbListing
from .vr import VRListing
from .website import WebsiteListing
from .sale import Sale

# This ensures all models are registered with SQLAlchemy
__all__ = [
    'Product',
    'ProductStatus',
    'ProductCondition',
    'PlatformCommon',
    'ListingStatus',
    'SyncStatus',
    'EbayListing',
    'ReverbListing',
    'VRListing',
    'WebsiteListing',
    'Sale'
    'Shipping'
    # 'User'
]