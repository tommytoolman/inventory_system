"""
Script to migrate data from platform_category_mappings to normalized tables
"""
import asyncio
from sqlalchemy import text
from app.database import async_session
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def migrate_category_mappings():
    """Migrate data from old platform_category_mappings table to new normalized tables"""
    
    async with async_session() as session:
        try:
            # First, get all unique Reverb categories
            logger.info("Fetching unique Reverb categories...")
            result = await session.execute(text("""
                SELECT DISTINCT 
                    source_category_id as uuid,
                    source_category_name as name
                FROM platform_category_mappings
                WHERE source_platform = 'reverb'
                    AND source_category_id IS NOT NULL
                ORDER BY source_category_name
            """))
            
            reverb_categories = result.fetchall()
            logger.info(f"Found {len(reverb_categories)} unique Reverb categories")
            
            # Create a mapping of UUID to ID for the new reverb_categories table
            uuid_to_id = {}
            
            # Insert Reverb categories
            for cat in reverb_categories:
                result = await session.execute(text("""
                    INSERT INTO reverb_categories (uuid, name, full_path)
                    VALUES (:uuid, :name, :name)
                    ON CONFLICT (uuid) DO UPDATE SET name = EXCLUDED.name
                    RETURNING id
                """), {
                    "uuid": cat.uuid,
                    "name": cat.name
                })
                reverb_id = result.scalar()
                uuid_to_id[cat.uuid] = reverb_id
            
            await session.commit()
            logger.info(f"Inserted {len(uuid_to_id)} Reverb categories")
            
            # Now migrate eBay mappings
            logger.info("Migrating eBay mappings...")
            result = await session.execute(text("""
                SELECT 
                    source_category_id,
                    target_category_id,
                    target_category_name,
                    confidence_score,
                    is_verified,
                    notes
                FROM platform_category_mappings
                WHERE source_platform = 'reverb'
                    AND target_platform = 'ebay'
                    AND source_category_id IS NOT NULL
                    AND target_category_id IS NOT NULL
            """))
            
            ebay_mappings = result.fetchall()
            ebay_count = 0
            
            for mapping in ebay_mappings:
                reverb_id = uuid_to_id.get(mapping.source_category_id)
                if reverb_id:
                    await session.execute(text("""
                        INSERT INTO ebay_category_mappings 
                        (reverb_category_id, ebay_category_id, ebay_category_name, 
                         confidence_score, is_verified, notes)
                        VALUES (:reverb_id, :ebay_id, :ebay_name, :confidence, :verified, :notes)
                        ON CONFLICT DO NOTHING
                    """), {
                        "reverb_id": reverb_id,
                        "ebay_id": mapping.target_category_id,
                        "ebay_name": mapping.target_category_name,
                        "confidence": mapping.confidence_score,
                        "verified": mapping.is_verified,
                        "notes": mapping.notes
                    })
                    ebay_count += 1
            
            await session.commit()
            logger.info(f"Migrated {ebay_count} eBay mappings")
            
            # Migrate Shopify mappings
            logger.info("Migrating Shopify mappings...")
            result = await session.execute(text("""
                SELECT 
                    source_category_id,
                    shopify_gid,
                    target_category_name,
                    merchant_type,
                    confidence_score,
                    is_verified,
                    notes
                FROM platform_category_mappings
                WHERE source_platform = 'reverb'
                    AND target_platform = 'shopify'
                    AND source_category_id IS NOT NULL
                    AND shopify_gid IS NOT NULL
            """))
            
            shopify_mappings = result.fetchall()
            shopify_count = 0
            
            for mapping in shopify_mappings:
                reverb_id = uuid_to_id.get(mapping.source_category_id)
                if reverb_id:
                    await session.execute(text("""
                        INSERT INTO shopify_category_mappings 
                        (reverb_category_id, shopify_gid, shopify_category_name, 
                         merchant_type, confidence_score, is_verified, notes)
                        VALUES (:reverb_id, :gid, :name, :merchant, :confidence, :verified, :notes)
                        ON CONFLICT DO NOTHING
                    """), {
                        "reverb_id": reverb_id,
                        "gid": mapping.shopify_gid,
                        "name": mapping.target_category_name,
                        "merchant": mapping.merchant_type,
                        "confidence": mapping.confidence_score,
                        "verified": mapping.is_verified,
                        "notes": mapping.notes
                    })
                    shopify_count += 1
            
            await session.commit()
            logger.info(f"Migrated {shopify_count} Shopify mappings")
            
            # Migrate VR mappings
            logger.info("Migrating V&R mappings...")
            result = await session.execute(text("""
                SELECT 
                    source_category_id,
                    vr_category_id,
                    vr_subcategory_id,
                    vr_sub_subcategory_id,
                    vr_sub_sub_subcategory_id,
                    target_category_name,
                    confidence_score,
                    is_verified,
                    notes
                FROM platform_category_mappings
                WHERE source_platform = 'reverb'
                    AND target_platform = 'vintageandrare'
                    AND source_category_id IS NOT NULL
                    AND vr_category_id IS NOT NULL
            """))
            
            vr_mappings = result.fetchall()
            vr_count = 0
            
            # Load VR category names
            import json
            from pathlib import Path
            vr_names_file = Path(__file__).parent / "mapping_work" / "vr_category_map.json"
            vr_names = {}
            if vr_names_file.exists():
                with open(vr_names_file, 'r') as f:
                    vr_names = json.load(f)
            
            for mapping in vr_mappings:
                reverb_id = uuid_to_id.get(mapping.source_category_id)
                if reverb_id:
                    # Get category names from JSON
                    cat_name = vr_names.get(mapping.vr_category_id, {}).get('name')
                    subcat_name = None
                    if mapping.vr_subcategory_id and mapping.vr_category_id in vr_names:
                        subcat_name = vr_names[mapping.vr_category_id].get('subcategories', {}).get(mapping.vr_subcategory_id, {}).get('name')
                    
                    await session.execute(text("""
                        INSERT INTO vr_category_mappings 
                        (reverb_category_id, vr_category_id, vr_category_name,
                         vr_subcategory_id, vr_subcategory_name,
                         vr_sub_subcategory_id, vr_sub_sub_subcategory_id,
                         confidence_score, is_verified, notes)
                        VALUES (:reverb_id, :cat_id, :cat_name, :subcat_id, :subcat_name,
                                :sub_subcat_id, :sub_sub_subcat_id,
                                :confidence, :verified, :notes)
                        ON CONFLICT DO NOTHING
                    """), {
                        "reverb_id": reverb_id,
                        "cat_id": mapping.vr_category_id,
                        "cat_name": cat_name,
                        "subcat_id": mapping.vr_subcategory_id,
                        "subcat_name": subcat_name,
                        "sub_subcat_id": mapping.vr_sub_subcategory_id,
                        "sub_sub_subcat_id": mapping.vr_sub_sub_subcategory_id,
                        "confidence": mapping.confidence_score,
                        "verified": mapping.is_verified,
                        "notes": mapping.notes
                    })
                    vr_count += 1
            
            await session.commit()
            logger.info(f"Migrated {vr_count} V&R mappings")
            
            # Print summary
            logger.info("\nMigration Summary:")
            logger.info(f"  Reverb categories: {len(uuid_to_id)}")
            logger.info(f"  eBay mappings: {ebay_count}")
            logger.info(f"  Shopify mappings: {shopify_count}")
            logger.info(f"  V&R mappings: {vr_count}")
            
            # Verify the migration
            result = await session.execute(text("SELECT COUNT(*) FROM reverb_categories"))
            rev_count = result.scalar()
            
            result = await session.execute(text("SELECT COUNT(*) FROM ebay_category_mappings"))
            ebay_verify = result.scalar()
            
            result = await session.execute(text("SELECT COUNT(*) FROM shopify_category_mappings"))
            shopify_verify = result.scalar()
            
            result = await session.execute(text("SELECT COUNT(*) FROM vr_category_mappings"))
            vr_verify = result.scalar()
            
            logger.info("\nDatabase Verification:")
            logger.info(f"  reverb_categories: {rev_count}")
            logger.info(f"  ebay_category_mappings: {ebay_verify}")
            logger.info(f"  shopify_category_mappings: {shopify_verify}")
            logger.info(f"  vr_category_mappings: {vr_verify}")
            
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            await session.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(migrate_category_mappings())