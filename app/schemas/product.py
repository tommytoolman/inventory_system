from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, validator
from enum import Enum
from datetime import datetime

class ProductStatus(str, Enum):
    """Product status values that match the database enum"""
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SOLD = "SOLD"
    ARCHIVED = "ARCHIVED"

class ProductCondition(str, Enum):
    """Product condition values that match the database enum"""
    NEW = "NEW"
    EXCELLENT = "EXCELLENT"
    VERY_GOOD = "VERYGOOD"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"

class ProductBase(BaseModel):
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
    
    # Media and links
    primary_image: Optional[str] = None
    additional_images: Optional[List[str]] = []
    video_url: Optional[str] = None
    external_link: Optional[str] = None
    
    # Additional fields
    processing_time: Optional[int] = None
    platform_data: Optional[Dict[str, Dict[str, Any]]] = {}
    
    @validator('base_price', 'cost_price', 'price', 'price_notax', 'collective_discount', 'offer_discount', pre=True)
    def validate_price(cls, v):
        """Ensure prices are valid floats"""
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            raise ValueError('Price must be a valid number')
    
    @validator('year', 'decade', 'processing_time', pre=True)
    def validate_integers(cls, v):
        """Ensure integer fields are valid integers"""
        if v is None or v == '':
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            raise ValueError('Value must be a valid integer')
    
    @validator('additional_images', pre=True)
    def validate_additional_images(cls, v):
        """Ensure additional_images is a list"""
        if v is None:
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            # Handle JSON string
            import json
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                # If it's not JSON, it might be a newline-separated list
                if '\n' in v:
                    return [url.strip() for url in v.split('\n') if url.strip()]
                return [v]
        return []
    
    @validator('platform_data', pre=True)
    def validate_platform_data(cls, v):
        """Ensure platform_data is a dictionary"""
        if v is None:
            return {}
        if isinstance(v, dict):
            return v
        if isinstance(v, str):
            # Handle JSON string
            import json
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                pass
        return {}
    
    @validator('condition', pre=True)
    def validate_condition(cls, v):
        """Handle condition value properly"""
        if v is None:
            raise ValueError('Condition is required')
        try:
            # Try to convert string to enum
            if isinstance(v, str):
                return ProductCondition(v)
            return v
        except ValueError:
            raise ValueError(f'Invalid condition: {v}')
    
    @validator('status', pre=True)
    def validate_status(cls, v):
        """Handle status value properly"""
        if v is None:
            return ProductStatus.DRAFT
        try:
            # Try to convert string to enum
            if isinstance(v, str):
                return ProductStatus(v)
            return v
        except ValueError:
            raise ValueError(f'Invalid status: {v}')
    
    class Config:
        """Configuration for Pydantic model"""
        from_attributes = True  # Allow conversion from ORM objects (replacement for orm_mode)

class ProductCreate(ProductBase):
    """Model for creating a new product"""
    # Using the base model with no changes
    pass

class ProductUpdate(BaseModel):
    """Model for updating an existing product"""
    sku: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    category: Optional[str] = None
    
    # Optional fields
    year: Optional[int] = None
    decade: Optional[int] = None
    finish: Optional[str] = None
    description: Optional[str] = None
    
    # Pricing
    base_price: Optional[float] = None
    cost_price: Optional[float] = None
    price: Optional[float] = None
    price_notax: Optional[float] = None
    collective_discount: Optional[float] = None
    offer_discount: Optional[float] = None
    
    # Status and flags
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
    
    # Media and links
    primary_image: Optional[str] = None
    additional_images: Optional[List[str]] = None
    video_url: Optional[str] = None
    external_link: Optional[str] = None
    
    # Additional fields
    processing_time: Optional[int] = None
    platform_data: Optional[Dict[str, Dict[str, Any]]] = None
    
    # Duplicate validators instead of referencing them
    @validator('base_price', 'cost_price', 'price', 'price_notax', 'collective_discount', 'offer_discount', pre=True)
    def validate_price(cls, v):
        """Ensure prices are valid floats"""
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            raise ValueError('Price must be a valid number')
    
    @validator('year', 'decade', 'processing_time', pre=True)
    def validate_integers(cls, v):
        """Ensure integer fields are valid integers"""
        if v is None or v == '':
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            raise ValueError('Value must be a valid integer')
    
    @validator('additional_images', pre=True)
    def validate_additional_images(cls, v):
        """Ensure additional_images is a list"""
        if v is None:
            return None
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            # Handle JSON string
            import json
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                # If it's not JSON, it might be a newline-separated list
                if '\n' in v:
                    return [url.strip() for url in v.split('\n') if url.strip()]
                return [v]
        return []
    
    @validator('platform_data', pre=True)
    def validate_platform_data(cls, v):
        """Ensure platform_data is a dictionary"""
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        if isinstance(v, str):
            # Handle JSON string
            import json
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                pass
        return {}
    
    @validator('condition', pre=True)
    def validate_condition(cls, v):
        """Handle condition value properly"""
        if v is None:
            return None
        try:
            # Try to convert string to enum
            if isinstance(v, str):
                return ProductCondition(v)
            return v
        except ValueError:
            raise ValueError(f'Invalid condition: {v}')
    
    @validator('status', pre=True)
    def validate_status(cls, v):
        """Handle status value properly"""
        if v is None:
            return None
        try:
            # Try to convert string to enum
            if isinstance(v, str):
                return ProductStatus(v)
            return v
        except ValueError:
            raise ValueError(f'Invalid status: {v}')
    
    class Config:
        """Configuration for Pydantic model"""
        validate_assignment = True
        from_attributes = True  # Replacement for orm_mode

class ProductRead(ProductBase):
    """Model for reading a product (for backward compatibility)"""
    id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        """Configuration for Pydantic model"""
        from_attributes = True  # Replacement for orm_mode

class ProductResponse(ProductBase):
    """Model for returning a product"""
    id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        """Configuration for Pydantic model"""
        from_attributes = True  # Replacement for orm_mode

class ProductSummary(BaseModel):
    """Model for returning a summary of a product"""
    id: int
    sku: str
    brand: str
    model: str
    primary_image: Optional[str] = None
    base_price: float
    status: ProductStatus
    
    class Config:
        """Configuration for Pydantic model"""
        from_attributes = True  # Replacement for orm_mode