from .activity_log import ActivityLog
from .product import Product, ProductStatus, ProductCondition
from .platform_common import PlatformCommon, ListingStatus, SyncStatus
from .ebay import EbayListing
from .reverb import ReverbListing
from .vr import VRListing
from .shopify import ShopifyListing
from .sale import Sale
from .category_mapping import CategoryMapping 
from .product_mapping import ProductMapping   
from .order import Order
from .shipping import Shipment, ShippingProfile
from .sync_event import SyncEvent
from .platform_status_mapping import PlatformStatusMapping
from .sync_stats import SyncStats

# from .product_merges import ProductMerge # We don't currently have a model for this.
# from .user import User  # Want to add this before we go live 

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
    'ShopifyListing',
    'Sale',
    'CategoryMapping',
    'ProductMapping',
    'Order',
    'Shipment', 
    'ShippingProfile',
    'ProductMerge',
    'SyncEvent',
    'ActivityLog',
    'PlatformStatusMapping',
    'SyncStats',
    # 'User',  
]