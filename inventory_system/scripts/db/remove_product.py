#!/usr/bin/env python3
"""
Remove a product from the database completely.
This will remove it from all platform listing tables, platform_common, and finally products table.

Usage:
    python scripts/remove_product_538.py 538
    python scripts/remove_product_538.py 538 --dry-run
    python scripts/remove_product_538.py --product-id 538
"""

import asyncio
import argparse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.database import async_session

async def remove_product(product_id: int, dry_run: bool = False):
    """Remove a product from all tables in the correct order"""
    async with async_session() as session:

        try:
            # Start transaction
            await session.begin()

            print(f"{'[DRY RUN] ' if dry_run else ''}Removing product {product_id} from database...\n")

            # 1. First, get platform_common IDs for this product
            platform_common_query = text("""
                SELECT id, platform_name, external_id
                FROM platform_common
                WHERE product_id = :product_id
            """)
            result = await session.execute(platform_common_query, {"product_id": product_id})
            platform_entries = result.fetchall()

            if not platform_entries:
                print(f"No platform_common entries found for product {product_id}")
            else:
                print(f"Found {len(platform_entries)} platform_common entries:")
                for entry in platform_entries:
                    print(f"  - {entry.platform_name}: platform_id={entry.id}, external_id={entry.external_id}")

            # 2. Remove from platform-specific listing tables
            for entry in platform_entries:
                platform_id = entry.id
                platform_name = entry.platform_name

                # Determine the correct table name
                if platform_name == 'reverb':
                    table_name = 'reverb_listings'
                elif platform_name == 'ebay':
                    table_name = 'ebay_listings'
                elif platform_name == 'shopify':
                    table_name = 'shopify_listings'
                elif platform_name == 'vr':
                    table_name = 'vr_listings'
                else:
                    print(f"  ⚠️  Unknown platform: {platform_name}")
                    continue

                # Delete from platform-specific table
                delete_listing_query = text(f"""
                    DELETE FROM {table_name}
                    WHERE platform_id = :platform_id
                """)

                if not dry_run:
                    result = await session.execute(delete_listing_query, {"platform_id": platform_id})
                    print(f"  ✓ Deleted from {table_name}: {result.rowcount} rows")
                else:
                    print(f"  [DRY RUN] Would delete from {table_name} where platform_id={platform_id}")

            # 3. Remove from platform_common
            delete_platform_common_query = text("""
                DELETE FROM platform_common
                WHERE product_id = :product_id
            """)

            if not dry_run:
                result = await session.execute(delete_platform_common_query, {"product_id": product_id})
                print(f"\n✓ Deleted from platform_common: {result.rowcount} rows")
            else:
                print(f"\n[DRY RUN] Would delete {len(platform_entries)} rows from platform_common")

            # 4. Finally, remove from products table
            delete_product_query = text("""
                DELETE FROM products
                WHERE id = :product_id
            """)

            if not dry_run:
                result = await session.execute(delete_product_query, {"product_id": product_id})
                print(f"✓ Deleted from products: {result.rowcount} rows")

                # Commit the transaction
                await session.commit()
                print(f"\n✅ Successfully removed product {product_id} from the database!")
            else:
                print(f"[DRY RUN] Would delete product {product_id} from products table")
                print("\n[DRY RUN] No changes were made to the database")

        except Exception as e:
            await session.rollback()
            print(f"\n❌ Error removing product: {str(e)}")
            raise

async def main():
    parser = argparse.ArgumentParser(description='Remove a product from database completely')
    parser.add_argument('product_id', nargs='?', type=int,
                       help='Product ID to remove')
    parser.add_argument('--product-id', dest='product_id_flag', type=int,
                       help='Product ID to remove (alternative syntax)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be deleted without actually deleting')

    args = parser.parse_args()

    # Get product ID from either positional arg or flag
    product_id = args.product_id or args.product_id_flag
    if not product_id:
        parser.error('Product ID is required. Use: script.py 123 or script.py --product-id 123')

    # First, check what will be deleted
    async with async_session() as session:
        # Count platform entries
        count_query = text("""
            SELECT COUNT(*) as platform_count
            FROM platform_common
            WHERE product_id = :product_id
        """)
        result = await session.execute(count_query, {"product_id": product_id})
        platform_count = result.scalar()

        # Check if product exists
        product_query = text("""
            SELECT sku, brand, model
            FROM products
            WHERE id = :product_id
        """)
        result = await session.execute(product_query, {"product_id": product_id})
        product_info = result.fetchone()

        if not product_info:
            print(f"❌ Product {product_id} not found in database")
            return

        print(f"\nProduct {product_id}: {product_info.brand} {product_info.model} (SKU: {product_info.sku})")
        print(f"Found {platform_count} platform listings")

    # Confirm before proceeding (unless dry-run)
    if not args.dry_run:
        response = input(f"\n⚠️  WARNING: This will permanently delete:\n"
                        f"  - {platform_count} platform listing entries\n"
                        f"  - {platform_count} platform_common entries\n"
                        f"  - 1 product entry\n"
                        f"\nThe listings will remain online on their platforms.\n"
                        f"Are you sure you want to continue? (yes/no): ")
        if response.lower() != 'yes':
            print("Cancelled")
            return

    await remove_product(product_id=product_id, dry_run=args.dry_run)

if __name__ == "__main__":
    asyncio.run(main())