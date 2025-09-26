"""
Utility functions for the application.
"""
import sqlalchemy
import re

from enum import Enum
from typing import Type, TypeVar, List, Optional, Dict, Any, Union
from pydantic import BaseModel
from sqlalchemy.orm import Query
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar('T', bound=BaseModel)
M = TypeVar('M')

async def model_to_schema(
    db_model: Any, 
    schema_class: Type[T],
    exclude: List[str] = None
) -> T:
    """
    Convert a SQLAlchemy model instance to a Pydantic schema instance.
    
    Args:
        db_model: SQLAlchemy model instance
        schema_class: Pydantic schema class
        exclude: List of fields to exclude
        
    Returns:
        Instance of the Pydantic schema
    """
    exclude_set = set(exclude) if exclude else set()
    
    # In Pydantic v2, use from_attributes=True for SQLAlchemy models
    # exclude parameter is not supported in model_validate
    return schema_class.model_validate(
        db_model,
        from_attributes=True
    )

async def models_to_schemas(
    db_models: List[Any], 
    schema_class: Type[T],
    exclude: List[str] = None
) -> List[T]:
    """
    Convert a list of SQLAlchemy model instances to a list of Pydantic schema instances.
    
    Args:
        db_models: List of SQLAlchemy model instances
        schema_class: Pydantic schema class
        exclude: List of fields to exclude
        
    Returns:
        List of Pydantic schema instances
    """
    return [await model_to_schema(model, schema_class, exclude) for model in db_models]

async def paginate_query(
    query: Query,
    db: AsyncSession,
    page: int = 1,
    page_size: int = 10
) -> Dict[str, Any]:
    """
    Paginate a SQLAlchemy query.
    
    Args:
        query: SQLAlchemy query object
        db: Database session
        page: Page number (1-indexed)
        page_size: Number of items per page
        
    Returns:
        Dictionary with pagination information and items
    """
    # Get total count for pagination
    count_query = query.statement.with_only_columns([sqlalchemy.func.count()]).order_by(None)
    total = await db.scalar(count_query)
    
    # Apply pagination
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    
    # Execute query
    result = await db.execute(query)
    items = result.scalars().all()
    
    # Calculate pagination values
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1
    has_next = page < total_pages
    has_prev = page > 1
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_next": has_next,
        "has_prev": has_prev
    }
    
    
class ImageQuality(Enum):
    """Image quality/size options for different platforms"""
    THUMBNAIL = "thumbnail"      # Small thumbnails
    CARD = "card"               # Card/grid displays  
    LARGE = "large"             # Standard web display
    SUPERSIZE = "supersize"     # High quality
    MAX_RES = "max_res"         # Maximum resolution

class ImageTransformer:
    """Transform image URLs for different platforms and quality requirements"""
    
    @staticmethod
    def transform_reverb_url(url: str, quality: ImageQuality = ImageQuality.LARGE) -> str:
        """
        Transform Reverb image URL to different resolutions
        
        Args:
            url: Original Reverb image URL
            quality: Desired image quality/size
            
        Returns:
            str: Transformed URL for the specified quality, or None if input is None/empty
            
        Example:
            Original: https://rvb-img.reverb.com/image/upload/s--k5jtQgjw--/a_0/f_auto,t_large/v1748246175/image.jpg
            Max res: https://rvb-img.reverb.com/image/upload/s--k5jtQgjw--/v1748246175/image.jpg
        """
        if not url:
            return None  # Explicitly return None for empty/None URLs
        if 'reverb.com' not in url:
            return url  # Return original if not Reverb (best we have)
        
        # Cloudinary transformation mapping
        transformations = {
            ImageQuality.THUMBNAIL: "/a_0/t_card-square",
            ImageQuality.CARD: "/a_0/t_card",
            ImageQuality.LARGE: "/a_0/f_auto,t_large", 
            ImageQuality.SUPERSIZE: "/a_0/f_auto,t_supersize",
            ImageQuality.MAX_RES: ""  # No transformation = max resolution
        }
        
        # For MAX_RES, we want to remove ALL transformations between /upload/ and /v{numbers}/
        if quality == ImageQuality.MAX_RES:
            # Pattern to match everything between /upload/ and /v{numbers}/
            # This handles both patterns:
            # - /upload/s--xyz--/f_auto,t_large/v123/
            # - /upload/a_0/f_auto,t_large/v123/
            pattern = r'/upload/.*?(/v\d+/)'
            match = re.search(pattern, url)
            if match:
                # Replace with just /upload/v{numbers}/
                return url[:url.find('/upload/')] + '/upload' + match.group(1) + url[match.end():]
            else:
                # Fallback if no version pattern found
                return url
        
        # For other qualities, remove existing transformations and add new ones
        # First remove any existing transformation patterns
        # Pattern 1: /s--xyz--/anything/
        url = re.sub(r'/s--[^/]+--/[^/]*/', '/', url)
        # Pattern 2: /a_0/anything/
        url = re.sub(r'/a_0/[^/]*/', '/', url)
        
        # Add new transformation
        transformation = transformations.get(quality, transformations[ImageQuality.LARGE])
        
        if transformation:
            # Insert transformation before the version number
            # Pattern: /v1748246175/ -> /TRANSFORMATION/v1748246175/
            version_pattern = r'(/v\d+/)'
            if re.search(version_pattern, url):
                return re.sub(version_pattern, f'{transformation}\\1', url)
            else:
                # Fallback: add transformation before filename
                return url.replace('/image/upload/', f'/image/upload{transformation}/')
        else:
            return url
    
    @staticmethod
    def transform_images_for_platform(image_urls: List[str], platform: str) -> List[str]:
        """
        Transform a list of image URLs for optimal quality for specific platforms
        
        Args:
            image_urls: List of original image URLs
            platform: Target platform ('vr', 'ebay', 'shopify', 'website')
            
        Returns:
            List[str]: Transformed URLs optimized for the platform
        """
        platform_quality_map = {
            'vr': ImageQuality.MAX_RES,      # V&R wants highest quality
            'ebay': ImageQuality.MAX_RES,   # eBay wants high quality
            'shopify': ImageQuality.MAX_RES,    # Shopify standard web quality
            'website': ImageQuality.MAX_RES,    # Your website standard quality
            'thumbnail': ImageQuality.THUMBNAIL  # For thumbnails/previews
        }
        
        quality = platform_quality_map.get(platform.lower(), ImageQuality.LARGE)
        
        return [
            ImageTransformer.transform_reverb_url(url, quality) 
            for url in image_urls if url
        ]
    
    @staticmethod
    def get_primary_image_for_platform(primary_image: Optional[str], platform: str) -> Optional[str]:
        """
        Get primary image URL optimized for specific platform
        
        Args:
            primary_image: Original primary image URL
            platform: Target platform
            
        Returns:
            Optional[str]: Transformed primary image URL
        """
        if not primary_image:
            return None
            
        return ImageTransformer.transform_images_for_platform([primary_image], platform)[0]


# Convenience functions for common use cases
def get_max_res_images(image_urls: List[str]) -> List[str]:
    """Get maximum resolution versions of image URLs"""
    return ImageTransformer.transform_images_for_platform(image_urls, 'vr')

def get_vr_optimized_images(primary_image: Optional[str], additional_images: List[str]) -> tuple[Optional[str], List[str]]:
    """Get V&R optimized images (max resolution)"""
    vr_primary = ImageTransformer.get_primary_image_for_platform(primary_image, 'vr')
    vr_additional = ImageTransformer.transform_images_for_platform(additional_images, 'vr')
    return vr_primary, vr_additional

