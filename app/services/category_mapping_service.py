"""
Purpose: Manages the translation of category identifiers between your internal system and external platforms (eBay, Reverb, V&R). 
This is essential because platforms don't always use the same category IDs or names.

Functionality: Provides methods to get_mapping (by IDs), get_mapping_by_name (using fuzzy matching for flexibility), 
create_mapping, and get a get_default_mapping. It interacts directly with the CategoryMapping database model.

Role: A focused utility service providing crucial data mapping needed by other services when creating or updating listings on external platforms.
"""
from typing import Optional, Dict, List, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from app.models.category_mapping import CategoryMapping

class CategoryMappingService:
    """Service for managing category mappings between platforms"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_mapping(self, source_platform: str, source_id: str, target_platform: str) -> Optional[CategoryMapping]:
        """
        Get mapping from source category to target platform
        
        Args:
            source_platform: Source platform ('internal', 'reverb', etc.)
            source_id: Category ID in source platform
            target_platform: Target platform ('vr', 'ebay', etc.)
            
        Returns:
            CategoryMapping if found, None otherwise
        """
        query = select(CategoryMapping).where(
            CategoryMapping.source_platform == source_platform,
            CategoryMapping.source_id == source_id,
            CategoryMapping.target_platform == target_platform
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def get_mapping_by_name(self, source_platform: str, source_name: str, target_platform: str) -> Optional[CategoryMapping]:
        """
        Find mapping by source category name (fuzzy match)
        
        Args:
            source_platform: Source platform ('internal', 'reverb', etc.)
            source_name: Category name in source platform
            target_platform: Target platform ('vr', 'ebay', etc.)
            
        Returns:
            CategoryMapping if found, None otherwise
        """
        # Try exact match first
        query = select(CategoryMapping).where(
            CategoryMapping.source_platform == source_platform,
            CategoryMapping.source_name == source_name,
            CategoryMapping.target_platform == target_platform
        )
        result = await self.db.execute(query)
        mapping = result.scalar_one_or_none()
        
        if mapping:
            return mapping
        
        # Try partial matches
        query = select(CategoryMapping).where(
            CategoryMapping.source_platform == source_platform,
            CategoryMapping.target_platform == target_platform
        )
        result = await self.db.execute(query)
        mappings = result.scalars().all()
        
        # Find best partial match
        best_match = None
        best_score = 0
        
        for m in mappings:
            if source_name.lower() in m.source_name.lower() or m.source_name.lower() in source_name.lower():
                # Simple scoring - length of the matching part divided by length of the longer string
                score = min(len(source_name), len(m.source_name)) / max(len(source_name), len(m.source_name))
                if score > best_score:
                    best_score = score
                    best_match = m
        
        # Only return if score is good enough
        if best_score > 0.6:  # Threshold for fuzzy matching
            return best_match
        
        return None
    
    async def create_mapping(self, mapping_data: Dict[str, Any]) -> CategoryMapping:
        """
        Create a new category mapping
        
        Args:
            mapping_data: Mapping data dictionary
            
        Returns:
            Created CategoryMapping
        """
        mapping = CategoryMapping(**mapping_data)
        self.db.add(mapping)
        await self.db.flush()
        return mapping
    
    async def get_default_mapping(self, target_platform: str) -> Optional[CategoryMapping]:
        """
        Get default mapping for a target platform
        
        Args:
            target_platform: Target platform ('vr', 'ebay', etc.)
            
        Returns:
            Default CategoryMapping if defined, None otherwise
        """
        query = select(CategoryMapping).where(
            CategoryMapping.source_platform == "default",
            CategoryMapping.target_platform == target_platform
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()