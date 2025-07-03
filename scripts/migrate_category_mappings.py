#!/usr/bin/env python3
"""
Migrate category mappings from JSON files to database
"""

import asyncio
import json
import os
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent))

from app.database import async_session
from app.services.category_mapping_service import CategoryMappingService

async def migrate_mappings():
    """Migrate all JSON mappings to database"""
    
    async with async_session() as db:
        service = CategoryMappingService(db)
        
        # Load and migrate reverb mappings
        reverb_file = "data/category_mappings/reverb_to_shopify.json"
        if os.path.exists(reverb_file):
            with open(reverb_file, 'r') as f:
                config = json.load(f)
            
            for mapping in config.get('mappings', []):
                await service.add_mapping(
                    source_platform='reverb',
                    source_category_id=mapping['source_category_id'],
                    source_category_name=mapping['source_category_name'],
                    target_platform='shopify',
                    target_category_id=mapping['target_category_id'],
                    target_category_name=mapping['target_category_name'],
                    target_category_path=mapping['target_category_path'],
                    merchant_type=mapping.get('merchant_type'),
                    confidence_level=mapping.get('confidence_level', 'manual'),
                    created_by='migration_script'
                )
        
        print("Migration completed!")

if __name__ == "__main__":
    asyncio.run(migrate_mappings())