#!/usr/bin/env python3
"""
CLI tool for managing Reverb listings.

Usage:
    python scripts/reverb/manage_reverb_listings.py end --reverb-id 123456
    python scripts/reverb/manage_reverb_listings.py end --sku REV-123456
    python scripts/reverb/manage_reverb_listings.py end --reverb-id 123456 --reason reverb_sale
    python scripts/reverb/manage_reverb_listings.py list --status live
    python scripts/reverb/manage_reverb_listings.py list --status all
"""

import asyncio
import argparse
import sys
from typing import Optional
from sqlalchemy import select, and_
from app.database import async_session
from app.models.reverb import ReverbListing
from app.models.platform_common import PlatformCommon
from app.models.product import Product
from app.services.reverb.client import ReverbClient
from app.core.config import get_settings

async def end_listing(reverb_id: Optional[str] = None, sku: Optional[str] = None, reason: str = "not_sold", dry_run: bool = False):
    """End a Reverb listing by Reverb ID or SKU"""

    if not reverb_id and not sku:
        print("❌ Error: Must provide either --reverb-id or --sku")
        return False

    async with async_session() as session:
        if sku:
            # Find by SKU
            query = (
                select(ReverbListing)
                .join(PlatformCommon, ReverbListing.platform_id == PlatformCommon.id)
                .join(Product, PlatformCommon.product_id == Product.id)
                .where(Product.sku == sku)
                .where(ReverbListing.reverb_state == 'live')
            )
        else:
            # Find by Reverb ID
            query = (
                select(ReverbListing)
                .where(ReverbListing.reverb_listing_id == reverb_id)
                .where(ReverbListing.reverb_state == 'live')
            )

        result = await session.execute(query)
        listing = result.scalar_one_or_none()

        if not listing:
            print(f"❌ No live Reverb listing found for {'SKU ' + sku if sku else 'ID ' + reverb_id}")
            return False

        # Get product info for display
        if sku:
            product_info = f"SKU: {sku}"
        else:
            pc_query = (
                select(Product)
                .join(PlatformCommon, Product.id == PlatformCommon.product_id)
                .where(PlatformCommon.id == listing.platform_id)
            )
            pc_result = await session.execute(pc_query)
            product = pc_result.scalar_one_or_none()
            product_info = f"Product: {product.brand} {product.model} (SKU: {product.sku})" if product else "Product: Unknown"

        print(f"\n📋 Listing Details:")
        print(f"   Reverb ID: {listing.reverb_listing_id}")
        print(f"   {product_info}")
        print(f"   State: {listing.reverb_state}")
        print(f"   Reason: {reason}")

        if dry_run:
            print(f"\n[DRY RUN] Would end Reverb listing {listing.reverb_listing_id}")
            return True

        # Confirm action
        confirm = input(f"\n⚠️  Are you sure you want to end this listing? (yes/no): ")
        if confirm.lower() != 'yes':
            print("Cancelled")
            return False

        # End the listing via API
        try:
            settings = get_settings()
            client = ReverbClient(api_key=settings.REVERB_API_KEY)

            print(f"\n🔄 Ending Reverb listing {listing.reverb_listing_id}...")
            response = await client.end_listing(listing.reverb_listing_id, reason)

            # Update local state
            listing.reverb_state = 'ended'
            await session.commit()

            print(f"✅ Successfully ended Reverb listing {listing.reverb_listing_id}")
            return True

        except Exception as e:
            print(f"❌ Error ending listing: {str(e)}")
            return False

async def list_listings(status: str = "live"):
    """List Reverb listings by status"""

    async with async_session() as session:
        query = (
            select(ReverbListing, PlatformCommon, Product)
            .join(PlatformCommon, ReverbListing.platform_id == PlatformCommon.id)
            .join(Product, PlatformCommon.product_id == Product.id)
        )

        if status != "all":
            query = query.where(ReverbListing.reverb_state == status)

        query = query.order_by(Product.sku)

        result = await session.execute(query)
        listings = result.all()

        if not listings:
            print(f"No {status} Reverb listings found")
            return

        print(f"\n📋 Reverb Listings ({status}):")
        print(f"{'SKU':<15} {'Reverb ID':<12} {'Brand':<20} {'Model':<30} {'State':<10}")
        print("-" * 90)

        for listing, platform, product in listings:
            print(f"{product.sku:<15} {listing.reverb_listing_id:<12} {product.brand[:20]:<20} {product.model[:30]:<30} {listing.reverb_state:<10}")

        print(f"\nTotal: {len(listings)} listings")

async def main():
    parser = argparse.ArgumentParser(description='Manage Reverb listings')
    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # End listing command
    end_parser = subparsers.add_parser('end', help='End a Reverb listing')
    end_parser.add_argument('--reverb-id', help='Reverb listing ID')
    end_parser.add_argument('--sku', help='Product SKU')
    end_parser.add_argument('--reason', default='not_sold',
                           choices=['not_sold', 'reverb_sale'],
                           help='Reason for ending (default: not_sold)')
    end_parser.add_argument('--dry-run', action='store_true',
                           help='Show what would happen without making changes')

    # List command
    list_parser = subparsers.add_parser('list', help='List Reverb listings')
    list_parser.add_argument('--status', default='live',
                            choices=['live', 'ended', 'sold', 'all'],
                            help='Filter by status (default: live)')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == 'end':
        success = await end_listing(
            reverb_id=args.reverb_id,
            sku=args.sku,
            reason=args.reason,
            dry_run=args.dry_run
        )
        sys.exit(0 if success else 1)

    elif args.command == 'list':
        await list_listings(status=args.status)

if __name__ == "__main__":
    asyncio.run(main())