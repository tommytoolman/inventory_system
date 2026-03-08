# app/schemas/platform/woocommerce.py
"""
Pydantic schemas for WooCommerce integration.
Follows the same pattern as shopify.py / reverb.py.
"""

from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime
from decimal import Decimal


class WooCommerceListingCreateDTO(BaseModel):
    """Schema for creating a WooCommerce listing from a RIFF product."""
    name: str
    regular_price: Decimal
    description: Optional[str] = None
    short_description: Optional[str] = None
    sku: Optional[str] = None
    manage_stock: bool = True
    stock_quantity: int = 1
    images: List[Dict[str, str]] = []
    categories: List[Dict[str, Any]] = []
    meta_data: List[Dict[str, Any]] = []


class WooCommerceListingUpdateDTO(BaseModel):
    """Schema for updating a WooCommerce listing."""
    name: Optional[str] = None
    regular_price: Optional[Decimal] = None
    sale_price: Optional[Decimal] = None
    description: Optional[str] = None
    stock_quantity: Optional[int] = None
    status: Optional[str] = None  # publish, draft, pending, private
    images: Optional[List[Dict[str, str]]] = None


class WooCommerceListingStatusDTO(BaseModel):
    """Schema for WooCommerce listing status response."""
    listing_id: int
    wc_product_id: Optional[str] = None
    status: str
    last_synced_at: Optional[datetime] = None
    sync_message: Optional[str] = None


class WooCommerceProductDTO(BaseModel):
    """Schema representing a WooCommerce product from the API."""
    id: int
    name: str
    slug: str
    permalink: Optional[str] = None
    type: str = "simple"
    status: str = "publish"
    sku: Optional[str] = None
    price: Optional[str] = None
    regular_price: Optional[str] = None
    sale_price: Optional[str] = None
    manage_stock: bool = False
    stock_quantity: Optional[int] = None
    stock_status: Optional[str] = None
    categories: List[Dict[str, Any]] = []
    images: List[Dict[str, Any]] = []
    description: Optional[str] = None
    short_description: Optional[str] = None
    total_sales: int = 0

    model_config = ConfigDict(from_attributes=True)


class WooCommerceStoreDTO(BaseModel):
    """Schema for WooCommerce store CRUD responses."""
    id: int
    name: str
    store_url: str
    is_active: bool = True
    sync_status: str = "healthy"
    last_sync_at: Optional[datetime] = None
    price_markup_percent: float = 0.0

    model_config = ConfigDict(from_attributes=True)


class WooCommerceStoreCreateDTO(BaseModel):
    """Schema for connecting a new WooCommerce store."""
    name: str
    store_url: str
    consumer_key: str
    consumer_secret: str
    webhook_secret: Optional[str] = ""
    price_markup_percent: float = 0.0


class WooCommerceOrderDTO(BaseModel):
    """Schema representing a WooCommerce order from the API."""
    id: int
    order_number: Optional[str] = None
    status: str
    total: Optional[str] = None
    currency: Optional[str] = None
    customer_id: Optional[int] = None
    billing: Optional[Dict[str, Any]] = None
    shipping: Optional[Dict[str, Any]] = None
    line_items: List[Dict[str, Any]] = []

    model_config = ConfigDict(from_attributes=True)
