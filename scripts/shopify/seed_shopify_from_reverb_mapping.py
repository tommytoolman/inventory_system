# scripts/seed_shopify_from_reverb_mapping.py
import os, sys, csv, argparse, asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

# Ensure the app path is added to resolve imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import async_session
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.models.shopify import ShopifyListing

load_dotenv()
DEFAULT_MAPPING_FILE = "scripts/reverb_to_shopify.csv"
SKIP_TOKEN = "#N/A"

def utc_naive_now():
    """Returns a timezone-naive UTC datetime object."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

def read_mapping(path: str, limit: Optional[int] = None) -> Tuple[List[Tuple[str,str]], Dict]:
    """Reads the reverb_id, shopify_id mapping from a CSV file."""
    rows: List[Tuple[str,str]] = []
    seen_reverb = set()
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        # Check for required headers
        if not reader.fieldnames or not {"reverb_id", "shopify_id"}.issubset(set(reader.fieldnames)):
            print("❌ Missing required columns: 'reverb_id' and 'shopify_id'")
            sys.exit(1)
            
        for row in reader:
            reverb_id = row.get("reverb_id", "").strip()
            shopify_id = row.get("shopify_id", "").strip()

            if not reverb_id or not shopify_id:
                continue
            
            # Simple duplicate check
            if reverb_id in seen_reverb:
                print(f"⚠️ Warning: Duplicate reverb_id found and skipped: {reverb_id}")
                continue
            seen_reverb.add(reverb_id)

            rows.append((reverb_id, shopify_id))
            if limit and len(rows) >= limit:
                break
    stats = {"mapping_rows_used": len(rows)}
    return rows, stats

async def get_product_id_from_reverb_external(session, reverb_external_id: str) -> Optional[int]:
    """Finds the master product_id using an existing Reverb listing ID."""
    q = select(PlatformCommon.product_id).where(
        PlatformCommon.platform_name == "reverb",
        PlatformCommon.external_id == reverb_external_id
    )
    res = await session.execute(q)
    return res.scalar_one_or_none()

async def upsert_platform_common_shopify(session, product_id: int, shopify_id: str) -> Tuple[int, bool]:
    """Creates or finds a platform_common entry for a Shopify listing."""
    q = select(PlatformCommon).where(
        PlatformCommon.platform_name == "shopify",
        PlatformCommon.external_id == shopify_id
    )
    res = await session.execute(q)
    existing = res.scalar_one_or_none()
    if existing:
        return existing.id, False # Return existing ID, not created
        
    now = utc_naive_now()
    pc = PlatformCommon(
        product_id=product_id,
        platform_name="shopify",
        external_id=shopify_id,
        status=ListingStatus.ACTIVE.value, # Assume active for initial seed
        sync_status=SyncStatus.SYNCED.value,
        last_sync=now
    )
    session.add(pc)
    await session.flush() # Flush to get the new ID
    return pc.id, True # Return new ID, created

async def upsert_shopify_listing(session, platform_id: int, shopify_id: str) -> bool:
    """Creates a minimal shopify_listings entry if one doesn't exist."""
    q = select(ShopifyListing).where(ShopifyListing.platform_id == platform_id)
    res = await session.execute(q)
    existing = res.scalar_one_or_none()
    if existing:
        return False # Not created

    now = utc_naive_now()
    
    # For this initial seed, we only populate the essential fields.
    # The rest can be populated later by a more detailed sync.
    listing = ShopifyListing(
        platform_id=platform_id,
        shopify_legacy_id=shopify_id,
        shopify_product_id=f"gid://shopify/Product/{shopify_id}",
        status=ListingStatus.ACTIVE.value,
        created_at=now,
        updated_at=now,
        last_synced_at=now,
        extended_attributes={"source": "reverb_mapping_seed", "seed_date": now.isoformat()}
    )
    session.add(listing)
    return True # Created

async def run(mapping_file: str, dry_run: bool, limit: Optional[int]):
    """Main execution function to run the seeding process."""
    print(f"📄 Using mapping file: {mapping_file}")
    rows, map_stats = read_mapping(mapping_file, limit=limit)
    print(f"🔢 Found {map_stats['mapping_rows_used']} usable mapping rows.")

    created_pc = existing_pc = 0
    created_shopify = existing_shopify = 0
    skipped_missing_reverb = 0
    processed = 0

    async with async_session() as session:
        for reverb_id, shopify_id in rows:
            processed += 1

            # Find the master product using the Reverb ID link
            product_id = await get_product_id_from_reverb_external(session, reverb_id)
            if not product_id:
                skipped_missing_reverb += 1
                print(f"❌ No product found for reverb_id={reverb_id}; skipping shopify_id={shopify_id}")
                continue

            if dry_run:
                print(f"DRY RUN: Would link product_id={product_id} to shopify_id={shopify_id}")
                created_pc += 1 # Simulate creation for summary
                created_shopify += 1
                continue

            # Upsert platform_common for Shopify
            pc_id, pc_created = await upsert_platform_common_shopify(session, product_id, shopify_id)
            if pc_created:
                created_pc += 1
            else:
                existing_pc += 1

            # Upsert the shopify_listings entry
            sl_created = await upsert_shopify_listing(session, pc_id, shopify_id)
            if sl_created:
                created_shopify += 1
            else:
                existing_shopify += 1

        if not dry_run:
            print("💾 Committing changes to the database...")
            await session.commit()

    print("\n===== Summary =====")
    print(f"Processed mapping rows:        {processed}")
    print(f"PlatformCommon created (shopify): {created_pc}")
    print(f"PlatformCommon existing:       {existing_pc}")
    print(f"Shopify listings created:      {created_shopify}")
    print(f"Shopify listings existing:     {existing_shopify}")
    print(f"Skipped (no Reverb match):     {skipped_missing_reverb}")
    print(f"Dry run:                       {dry_run}")
    print("✅ Done.")

def parse_args():
    p = argparse.ArgumentParser(description="Seed Shopify platform entries from a Reverb→Shopify mapping file.")
    p.add_argument("--mapping-file", default=DEFAULT_MAPPING_FILE, help="Path to the CSV mapping file.")
    p.add_argument("--dry-run", action="store_true", help="Simulate only; no database writes.")
    p.add_argument("--limit", type=int, help="Process only the first N mapping rows.")
    return p.parse_args()

def main():
    args = parse_args()
    try:
        asyncio.run(run(
            mapping_file=args.mapping_file,
            dry_run=args.dry_run,
            limit=args.limit
        ))
    except (SQLAlchemyError, FileNotFoundError) as e:
        print(f"An error occurred: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nProcess interrupted by user.")

if __name__ == "__main__":
    main()