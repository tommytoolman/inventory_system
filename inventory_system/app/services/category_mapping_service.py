"""
Purpose: Manages the translation of category identifiers between your internal system and external platforms (eBay, Reverb, V&R). 
This is essential because platforms don't always use the same category IDs or names.

Functionality: Provides methods to get_mapping (by IDs), get_mapping_by_name (using fuzzy matching for flexibility), 
create_mapping, and get a get_default_mapping. It interacts directly with the CategoryMapping database model.

Role: A focused utility service providing crucial data mapping needed by other services when creating or updating listings on external platforms.
"""

import json
import os

from typing import Optional, Dict, List, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from app.models.category_mapping import CategoryMapping


class CategoryMappingService:
    """Service for managing category mappings between platforms"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self._cached_mappings = {}
        self.config_path = "data/category_mappings"
    
    async def get_mapping(self, source_platform: str, source_id: str, target_platform: str) -> Optional[CategoryMapping]:
        """
        Get mapping from source category to target platform
        
        Args:
            source_platform: Source platform ('internal', 'reverb', etc.)
            source_id: Category ID in source platform
            target_platform: Target platform ('vr', 'ebay', 'shopify', etc.)
            
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
            target_platform: Target platform ('vr', 'ebay', 'shopify', etc.)
            
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
            target_platform: Target platform ('vr', 'ebay', 'shopify', etc.)
            
        Returns:
            Default CategoryMapping if defined, None otherwise
        """
        query = select(CategoryMapping).where(
            CategoryMapping.source_platform == "default",
            CategoryMapping.target_platform == target_platform
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    # NEW METHODS FOR YOUR REVERB → SHOPIFY USE CASE
    
    async def get_reverb_to_shopify_mapping(self, reverb_category_uuid: str) -> Dict[str, str]:
        """
        Get Reverb to Shopify mapping with fallback to JSON config
        
        Args:
            reverb_category_uuid: Reverb category UUID
            
        Returns:
            Dict with shopify_category, shopify_gid, merchant_type
        """
        # Try database first
        db_mapping = await self.get_mapping('reverb', reverb_category_uuid, 'shopify')
        
        if db_mapping:
            return {
                'shopify_category': db_mapping.target_name,
                'shopify_gid': db_mapping.target_id,
                'merchant_type': db_mapping.mapping_metadata.get('merchant_type', 'Musical Instrument') if db_mapping.mapping_metadata else 'Musical Instrument'
            }
        
        # Fall back to JSON config
        return self._get_reverb_mapping_from_json(reverb_category_uuid)
    
    def _get_reverb_mapping_from_json(self, reverb_category_uuid: str) -> Dict[str, str]:
        """Get Reverb mapping from JSON configuration (your existing hardcoded mappings)"""
        
        # Your existing hardcoded mappings - moved here for centralization
        mappings = {
            # Amplifiers
            '10335451-31e5-418a-8ed8-f48cd738f17d': {
                'shopify_category': 'Arts & Entertainment > Hobbies & Creative Arts > Musical Instrument & Orchestra Accessories > Musical Instrument Amplifiers > Guitar Amplifiers',
                'shopify_gid': 'gid://shopify/TaxonomyCategory/ae-2-7-10-3',
                'merchant_type': 'Guitar Combo Amplifier'
            },
            # Electric Guitars
            'dfd39027-d134-4353-b9e4-57dc6be791b9': {
                'shopify_category': 'Arts & Entertainment > Hobbies & Creative Arts > Musical Instruments > String Instruments > Electric Guitars',
                'shopify_gid': 'gid://shopify/TaxonomyCategory/ae-2-8-7-2-4',
                'merchant_type': 'Electric Guitar'
            },
            # Add more of your mappings here...
        }
        
        if reverb_category_uuid in mappings:
            return mappings[reverb_category_uuid]
        
        # Fallback
        return {
            'shopify_category': 'Arts & Entertainment > Hobbies & Creative Arts > Musical Instruments',
            'shopify_gid': 'gid://shopify/TaxonomyCategory/ae-2-8',
            'merchant_type': 'Musical Instrument'
        }
    
    async def bulk_import_reverb_mappings(self, mappings_dict: Dict[str, Dict[str, str]]) -> int:
        """
        Bulk import Reverb to Shopify mappings into database
        
        Args:
            mappings_dict: Dictionary of UUID -> mapping data
            
        Returns:
            Number of mappings imported
        """
        imported_count = 0
        
        for reverb_uuid, mapping_data in mappings_dict.items():
            # Check if mapping already exists
            existing = await self.get_mapping('reverb', reverb_uuid, 'shopify')
            
            if not existing:
                new_mapping = CategoryMapping(
                    source_platform='reverb',
                    source_id=reverb_uuid,
                    source_name=mapping_data.get('reverb_category_name', ''),
                    target_platform='shopify',
                    target_id=mapping_data.get('shopify_gid', ''),
                    target_name=mapping_data.get('shopify_category', ''),
                    mapping_metadata={'merchant_type': mapping_data.get('merchant_type', '')},
                    created_at=datetime.now(timezone.utc)
                )
                
                self.db.add(new_mapping)
                imported_count += 1
        
        await self.db.commit()
        return imported_count