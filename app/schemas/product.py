"""
Schemas for product-related API endpoints. Refactored using Mixin.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, field_validator, ConfigDict
from datetime import datetime
import json # Import json at top level

from app.core.enums import ProductStatus, ProductCondition

class ProductValidationMixin(BaseModel):
    """
    --- Mixin class for shared validation logic ---
    Note: Placed common model_config here for DRYness
    """
    model_config = ConfigDict(
        from_attributes = True,
        populate_by_name = True
    )

    @field_validator('base_price', 'cost_price', 'price', 'price_notax', 'collective_discount', 'offer_discount', mode='before', check_fields=False)
    @classmethod # Added @classmethod as validators are often class methods
    def validate_price(cls, v):
        if v is None: 
            return None
        
            # Handle empty strings - convert to 0 or None
        if v == '' or v == 0:
            return 0.0  # or None if you prefer
        
        try: 
            return float(v)
        except (ValueError, TypeError): 
            raise ValueError('Price must be a valid number')

@field_validator('base_price', mode='before')
@classmethod
def validate_base_price(cls, v):
    """Base price is required - must be > 0"""
    if v == '' or v is None:
        raise ValueError('Base price is required')
    try:
        price = float(v)
        if price <= 0:
            raise ValueError('Base price must be greater than 0')
        return price
    except (ValueError, TypeError):
        raise ValueError(f'Base price must be a valid number, got: {v}')

    @field_validator('cost_price', 'price', 'price_notax', 'collective_discount', 'offer_discount', mode='before')
    @classmethod
    def validate_optional_price(cls, v):
        """Optional price fields - empty string becomes 0"""
        if v == '' or v is None:
            return 0.0
        try:
            return float(v)
        except (ValueError, TypeError):
            raise ValueError(f'Price must be a valid number, got: {v}')

    @field_validator('year', 'decade', 'processing_time', mode='before', check_fields=False)
    @classmethod # Added @classmethod
    def validate_integers(cls, v):
        if v is None or v == '': return None
        try: return int(v)
        except (ValueError, TypeError): raise ValueError('Value must be a valid integer')

    @field_validator('additional_images', mode='before', check_fields=False)
    @classmethod
    def validate_additional_images(cls, v):
        if v is None: return [] # Default to empty list if None
        if isinstance(v, list): return v
        if isinstance(v, str):
            try: return json.loads(v)
            except json.JSONDecodeError:
                if '\n' in v: return [url.strip() for url in v.split('\n') if url.strip()]
                return [v] # Wrap single string in list
        # Raise error for invalid types instead of returning []?
        # raise ValueError("additional_images must be None, list, JSON string, or newline-separated string")
        return [] # Current behavior: return [] for other invalid types

    @field_validator('platform_data', mode='before', check_fields=False)
    @classmethod
    def validate_platform_data(cls, v):
        if v is None: return {} # Default to empty dict if None
        if isinstance(v, dict): return v
        if isinstance(v, str):
            try: return json.loads(v)
            except json.JSONDecodeError: pass # Ignore errors, maybe return {} or raise?
        # Raise error for invalid types instead of returning {}?
        # raise ValueError("platform_data must be None, dict, or JSON string")
        return {} # Current behavior: return {} for other invalid types


class ProductBase(ProductValidationMixin): # Inherit Mixin (gets config + validators)
    """Base model for product data common to all operations"""
    sku: str
    brand: str
    model: str
    category: str

    # Optional fields
    year: Optional[int] = None
    decade: Optional[int] = None
    finish: Optional[str] = None
    description: Optional[str] = None

    # Pricing
    base_price: float
    cost_price: Optional[float] = None
    price: Optional[float] = None
    price_notax: Optional[float] = None
    collective_discount: Optional[float] = None
    offer_discount: Optional[float] = None

    # Status and flags
    status: ProductStatus = ProductStatus.DRAFT
    condition: ProductCondition
    is_sold: Optional[bool] = False
    in_collective: Optional[bool] = False
    in_inventory: Optional[bool] = True
    in_reseller: Optional[bool] = False
    free_shipping: Optional[bool] = False
    buy_now: Optional[bool] = True
    show_vat: Optional[bool] = True
    local_pickup: Optional[bool] = False
    available_for_shipment: Optional[bool] = True
    is_stocked_item: Optional[bool] = False
    quantity: Optional[int] = None
    shipping_profile_id: Optional[int] = None

    # Media and links
    primary_image: Optional[str] = None
    additional_images: Optional[List[str]] = [] # Default matches validator output
    video_url: Optional[str] = None
    external_link: Optional[str] = None

    # Additional fields
    processing_time: Optional[int] = None
    platform_data: Optional[Dict[str, Dict[str, Any]]] = {} # Default matches validator output

    # --- NO duplicated validators or model_config needed here ---


class ProductCreate(ProductBase):
    """Model for creating a new product"""
    # Inherits everything from ProductBase (including validation and config)
    pass


class ProductUpdate(ProductValidationMixin): # Inherit Mixin (gets config + validators)
    """Model for updating an existing product (PATCH). All fields are optional."""
    # --- List only the fields, all Optional. Validation comes from Mixin. ---
    sku: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    category: Optional[str] = None
    year: Optional[int] = None
    decade: Optional[int] = None
    finish: Optional[str] = None
    description: Optional[str] = None
    base_price: Optional[float] = None
    cost_price: Optional[float] = None
    price: Optional[float] = None
    price_notax: Optional[float] = None
    collective_discount: Optional[float] = None
    offer_discount: Optional[float] = None
    status: Optional[ProductStatus] = None
    condition: Optional[ProductCondition] = None
    is_sold: Optional[bool] = None
    in_collective: Optional[bool] = None
    in_inventory: Optional[bool] = None
    in_reseller: Optional[bool] = None
    free_shipping: Optional[bool] = None
    buy_now: Optional[bool] = None
    show_vat: Optional[bool] = None
    local_pickup: Optional[bool] = None
    available_for_shipment: Optional[bool] = None
    shipping_profile_id: Optional[int] = None
    primary_image: Optional[str] = None
    additional_images: Optional[List[str]] = None # Allows update to None or new list
    video_url: Optional[str] = None
    external_link: Optional[str] = None
    processing_time: Optional[int] = None
    platform_data: Optional[Dict[str, Dict[str, Any]]] = None # Allows update to None or new dict

    # --- NO duplicated validators or model_config needed here ---


class ProductRead(ProductBase): # Inherit ProductBase (which inherits Mixin)
    """Model for reading a product"""
    id: int
    created_at: datetime
    updated_at: datetime

    # --- model_config is inherited from ProductBase/Mixin
