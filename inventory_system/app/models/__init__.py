from .activity_log import ActivityLog
from .category_mapping import CategoryMapping
from .category_stats import CategoryVelocityStats, InventoryHealthSnapshot
from .condition_mapping import PlatformConditionMapping
from .ebay import EbayListing
from .ebay_order import EbayOrder
from .job import Job
from .listing_stats_history import ListingStatsHistory
from .order import Order
from .platform_common import ListingStatus, PlatformCommon, SyncStatus
from .platform_preference import PlatformPreference
from .platform_status_mapping import PlatformStatusMapping
from .product import Product, ProductCondition, ProductStatus
from .product_mapping import ProductMapping
from .reverb import ReverbListing
from .reverb_historical import ReverbHistoricalListing
from .reverb_order import ReverbOrder
from .sale import Sale
from .shipping import Shipment, ShippingProfile
from .shopify import ShopifyListing
from .shopify_order import ShopifyOrder
from .sync_error import SyncErrorRecord
from .sync_event import SyncEvent
from .sync_stats import SyncStats

# Tenant management models (Phase 1 multi-tenancy)
from .tenant import Tenant, TenantStatus
from .tenant_credential import CredentialType, TenantCredential
from .tenant_usage import TenantUsage
from .tenant_user import TenantRole, TenantUser
from .tenant_webhook import TenantWebhook
from .user import User
from .vr import VRListing
from .vr_job import VRJob, VRJobStatus
from .woocommerce import WooCommerceListing
from .woocommerce_order import WooCommerceOrder
from .woocommerce_store import WooCommerceStore

# from .product_merges import ProductMerge # We don't currently have a model for this.

# This ensures all models are registered with SQLAlchemy
__all__ = [
    "Product",
    "ProductStatus",
    "ProductCondition",
    "PlatformCommon",
    "ListingStatus",
    "SyncStatus",
    "EbayListing",
    "ReverbListing",
    "VRListing",
    "ShopifyListing",
    "WooCommerceListing",
    "Sale",
    "CategoryMapping",
    "ProductMapping",
    "Order",
    "Shipment",
    "ShippingProfile",
    "SyncEvent",
    "ActivityLog",
    "PlatformStatusMapping",
    "SyncStats",
    "Job",
    "PlatformConditionMapping",
    "VRJob",
    "VRJobStatus",
    "ListingStatsHistory",
    "ReverbHistoricalListing",
    "CategoryVelocityStats",
    "InventoryHealthSnapshot",
    "PlatformPreference",
    "SyncErrorRecord",
    "EbayOrder",
    "ReverbOrder",
    "ShopifyOrder",
    "WooCommerceOrder",
    "WooCommerceStore",
    "User",
    "Tenant",
    "TenantStatus",
    "TenantCredential",
    "CredentialType",
    "TenantUser",
    "TenantRole",
    "TenantUsage",
    "TenantWebhook",
]
