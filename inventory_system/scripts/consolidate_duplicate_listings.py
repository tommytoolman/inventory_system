#!/usr/bin/env python3
"""
Consolidate duplicate new listing sync events into a single product.
This handles cases where the same product appears as multiple new listings across platforms.

Usage:
    python scripts/consolidate_duplicate_listings.py --events 13003 13014 13016
    python scripts/consolidate_duplicate_listings.py --events 13003 13014 13016 --dry-run
"""

import asyncio
import argparse
from typing import List
from sqlalchemy import text, select
from app.database import async_session
from app.models.product import Product
from app.models.platform_common import PlatformCommon
from app.models.sync_event import SyncEvent
from app.services.product_service import ProductService
from datetime import datetime, timezone

async def consolidate_listings(event_ids: List[int], dry_run: bool = False, auto_confirm: bool = False):
    """Consolidate multiple new listing events into a single product"""

    async with async_session() as session:
        # 1. Fetch all the events
        query = text("""
            SELECT
                id,
                platform_name,
                external_id,
                change_data,
                sync_run_id
            FROM sync_events
            WHERE id = ANY(:event_ids)
            AND status = 'pending'
            AND change_type = 'new_listing'
            ORDER BY id
        """)

        result = await session.execute(query, {"event_ids": event_ids})
        events = result.fetchall()

        if len(events) != len(event_ids):
            print(f"❌ Expected {len(event_ids)} events but found {len(events)}")
            return

        print(f"Found {len(events)} events to consolidate:\n")

        # Display event details
        reverb_event = None
        for event in events:
            change_data = event.change_data
            print(f"Event {event.id} - {event.platform_name.upper()}:")
            print(f"  External ID: {event.external_id}")
            print(f"  Title: {change_data.get('title', 'N/A')}")
            print(f"  Price: {change_data.get('price', 'N/A')}")
            print()

            # Prefer Reverb as the primary source
            if event.platform_name == 'reverb':
                reverb_event = event

        # Use Reverb event as primary, or first event if no Reverb
        primary_event = reverb_event or events[0]
        primary_data = primary_event.change_data

        if dry_run:
            print("\n[DRY RUN] Would create product with:")
            print(f"  Primary source: {primary_event.platform_name.upper()}")
            print(f"  SKU: REV-{primary_event.external_id}")
            print(f"  Title: {primary_data.get('title', 'Unknown')}")
            print(f"  Brand: {primary_data.get('brand', 'Unknown')}")
            print(f"  Model: {primary_data.get('model', 'Unknown')}")
            print(f"  Price: {primary_data.get('price', 0)}")
            print("\nWould create platform links for:")
            for event in events:
                print(f"  - {event.platform_name.upper()}: {event.external_id}")
            return

        # Confirm before proceeding
        if not auto_confirm:
            response = input("\n⚠️  Create this product and consolidate listings? (yes/no): ")
            if response.lower() != 'yes':
                print("Cancelled")
                return

        # 2. Create the product
        product_service = ProductService(session)

        # Start with basic data from primary event
        product_data = {
            "sku": f"REV-{primary_event.external_id}",  # Always use REV- format
            "brand": primary_data.get('brand') or 'Unknown',
            "model": primary_data.get('model') or primary_data.get('title', 'Unknown'),
            "base_price": float(primary_data.get('price', 0)),
            "quantity": 1,
            "status": "ACTIVE",
            "category": primary_data.get('category'),
            "primary_image": primary_data.get('primary_image_url'),
            "additional_images": primary_data.get('additional_images', []),
            "condition": "VERYGOOD",  # Required field - defaulting to VERYGOOD
            "processing_time": 3,  # Default to 3 days
            "year": None,
            "finish": None,
            "title": None,
            "description": None,
            "decade": None
        }

        # Collect best data from all events
        all_titles = []
        all_images = []

        for event in events:
            data = event.change_data

            # Collect titles
            if data.get('title'):
                all_titles.append(data['title'])

            if event.platform_name == 'vr' and 'extended_attributes' in data:
                attrs = data['extended_attributes']

                # V&R has the most complete data
                if attrs.get('product_year'):
                    product_data['year'] = int(attrs['product_year'])
                    product_data['decade'] = (int(attrs['product_year']) // 10) * 10

                if attrs.get('product_finish'):
                    product_data['finish'] = attrs['product_finish']

                if attrs.get('category_name'):
                    product_data['category'] = attrs['category_name']

                if attrs.get('product_description'):
                    product_data['description'] = attrs['product_description']

                if attrs.get('processing_time'):
                    # Parse "3 Days" to 3
                    processing_str = attrs['processing_time']
                    if 'Day' in processing_str:
                        product_data['processing_time'] = int(processing_str.split()[0])
                    elif 'Week' in processing_str:
                        product_data['processing_time'] = int(processing_str.split()[0]) * 7

                # Parse V&R images
                if attrs.get('image_url'):
                    vr_images = attrs['image_url'].split('|')
                    all_images.extend(vr_images)

            elif event.platform_name == 'ebay':
                # eBay might have additional images
                raw = data.get('raw_data', {})
                if raw.get('PictureDetails', {}).get('GalleryURL'):
                    # This is just thumbnail, would need full API call for all images
                    pass

        # Use the most complete title (usually the longest one)
        if all_titles:
            product_data['title'] = max(all_titles, key=len)

        # Use all collected images
        if all_images:
            # First image becomes primary, rest become additional
            product_data['primary_image'] = all_images[0]
            if len(all_images) > 1:
                product_data['additional_images'] = all_images[1:]

        # Create product
        product = Product(**product_data)
        session.add(product)
        await session.flush()  # Get the product ID

        print(f"\n✅ Created product ID: {product.id}, SKU: {product.sku}")

        # 3. Create platform_common entries for each platform
        for event in events:
            # Generate or extract listing URL
            listing_url = event.change_data.get('listing_url')

            # Generate URL if not provided
            if not listing_url:
                if event.platform_name == 'reverb':
                    # Reverb URL pattern: https://reverb.com/item/{listing_id}
                    listing_url = f"https://reverb.com/item/{event.external_id}"
                elif event.platform_name == 'ebay':
                    # eBay URL should be in the data, but fallback to pattern if needed
                    listing_url = f"https://www.ebay.co.uk/itm/{event.external_id}"
                elif event.platform_name == 'vr':
                    # V&R URL pattern: https://www.vintageandrare.com/product/{product_id}
                    listing_url = f"https://www.vintageandrare.com/product/{event.external_id}"

            platform_common = PlatformCommon(
                product_id=product.id,
                platform_name=event.platform_name,
                external_id=event.external_id,
                status="ACTIVE",
                listing_url=listing_url,
                platform_specific_data={
                    "title": event.change_data.get('title'),
                    "price": event.change_data.get('price'),
                    "status": "active"
                },
                last_sync=datetime.utcnow()
            )
            session.add(platform_common)
            await session.flush()

            print(f"✅ Created {event.platform_name} platform link (ID: {platform_common.id})")

            # Create platform-specific listing entry (with duplicate check)
            if event.platform_name == 'reverb':
                # Create reverb_listings entry
                create_listing = text("""
                    INSERT INTO reverb_listings (platform_id, reverb_listing_id, reverb_state)
                    VALUES (:platform_id, :external_id, 'live')
                    ON CONFLICT (reverb_listing_id) DO NOTHING
                """)
                await session.execute(create_listing, {
                    "platform_id": platform_common.id,
                    "external_id": event.external_id
                })

            elif event.platform_name == 'ebay':
                # Create ebay_listings entry
                create_listing = text("""
                    INSERT INTO ebay_listings (platform_id, ebay_item_id)
                    VALUES (:platform_id, :external_id)
                    ON CONFLICT (ebay_item_id) DO NOTHING
                """)
                await session.execute(create_listing, {
                    "platform_id": platform_common.id,
                    "external_id": event.external_id
                })

            elif event.platform_name == 'vr':
                # Create vr_listings entry
                create_listing = text("""
                    INSERT INTO vr_listings (platform_id, vr_listing_id)
                    VALUES (:platform_id, :external_id)
                    ON CONFLICT (vr_listing_id) DO NOTHING
                """)
                await session.execute(create_listing, {
                    "platform_id": platform_common.id,
                    "external_id": event.external_id
                })

        # 4. Mark sync events as processed
        update_events = text("""
            UPDATE sync_events
            SET status = 'processed',
                processed_at = CURRENT_TIMESTAMP,
                product_id = :product_id,
                notes = 'Consolidated into single product'
            WHERE id = ANY(:event_ids)
        """)

        await session.execute(update_events, {
            "product_id": product.id,
            "event_ids": event_ids
        })

        await session.commit()

        print(f"\n✅ Successfully consolidated {len(events)} listings into product {product.id}")
        print(f"   SKU: {product.sku}")
        print(f"   Brand: {product.brand}")
        print(f"   Model: {product.model}")
        print("\n✅ All sync events marked as processed")

async def main():
    parser = argparse.ArgumentParser(description='Consolidate duplicate listings')
    parser.add_argument('--events', nargs='+', type=int, required=True,
                       help='Sync event IDs to consolidate')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would happen without making changes')
    parser.add_argument('--yes', action='store_true',
                       help='Auto-confirm without prompting')

    args = parser.parse_args()

    if len(args.events) < 2:
        parser.error("Need at least 2 events to consolidate")

    await consolidate_listings(args.events, args.dry_run, args.yes)

if __name__ == "__main__":
    asyncio.run(main())