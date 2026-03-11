#!/usr/bin/env python3
"""
Reconcile partial and error sync events.

This script handles cases where platform synchronization was only partially successful,
such as when a Reverb listing successfully synced to Shopify but failed on eBay.

FUNCTIONALITY:
1. Finds partial/error sync events (or processes a specific event by ID)
2. Handles missing product_id by performing SKU lookup (REV-{external_id})
3. Checks current platform status to detect manual fixes
4. Retries ONLY the failed platforms (won't create duplicates)
5. Updates event status:
   - 'processed' if all platforms now have listings
   - remains 'partial' if some platforms still missing
6. Maintains detailed notes with retry results

USAGE EXAMPLES:

    # Process all partial/error events
    python scripts/reconcile_partial_events.py
    
    # Process specific event
    python scripts/reconcile_partial_events.py --event-id 12300
    
    # Dry run to see what would happen
    python scripts/reconcile_partial_events.py --dry-run
    
    # Process only first 5 events
    python scripts/reconcile_partial_events.py --limit 5

COMMON SCENARIOS:

1. eBay listing failed due to shipping configuration:
   - Script will retry with correct Business Policies
   - Uses same configuration as UI "Create Listing" button
   
2. Event missing product_id (legacy events):
   - Script performs SKU lookup using REV-{external_id}
   - Updates event with found product_id for future use
   
3. Platform listing created manually after sync failure:
   - Script detects existing listing via platform_common check
   - Marks platform as complete without creating duplicate

OUTPUT EXAMPLE:
    Processing event 12300 (status: partial, type: new_listing)
      Platform: reverb, External ID: 91978708
      Product: REV-91978708 - Fender Stratocaster
      Price: £16,999
      
    === PLATFORM STATUS CHECK ===
      Checking EBAY: ❌ missing - will retry
      Checking SHOPIFY: ✓ already exists: 12253966172500
      Checking VR: ✓ already exists: created
      
    === RETRYING FAILED PLATFORMS ===
      Retrying EBAY...
      ✅ Successfully created ebay: 257107182856
      
    🎉 All platforms successful - marking event as PROCESSED
"""

import sys
import os
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import async_session
from app.core.config import get_settings
from app.models import SyncEvent, Product, PlatformCommon
from app.services.ebay_service import EbayService
from app.services.shopify_service import ShopifyService
from app.services.vr_service import VRService

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def check_platform_status(session: AsyncSession, product_id: int, platform: str) -> Optional[str]:
    """Check if a platform listing exists for a product."""
    stmt = select(PlatformCommon).where(
        and_(
            PlatformCommon.product_id == product_id,
            PlatformCommon.platform_name == platform,
            PlatformCommon.status.in_(['active', 'draft'])
        )
    )
    result = await session.execute(stmt)
    platform_common = result.scalar_one_or_none()
    
    if platform_common:
        return platform_common.external_id
    return None


async def retry_failed_platform(
    session: AsyncSession,
    product: Product,
    platform: str,
    reverb_data: Optional[Dict] = None
) -> Dict:
    """Retry creating a listing on a specific platform."""
    logger.info(f"  Retrying {platform} for product {product.sku}")
    
    try:
        # Get settings for services
        settings = get_settings()
        
        if platform == 'ebay':
            ebay_service = EbayService(session, settings)
            
            # Use the corrected profile IDs
            policies = {
                'shipping_profile_id': '252277357017',
                'payment_profile_id': '252544577017',
                'return_profile_id': '252277356017'
            }
            
            # Check for product-specific policies
            if hasattr(product, 'platform_data') and product.platform_data and 'ebay' in product.platform_data:
                ebay_data = product.platform_data['ebay']
                if ebay_data.get('shipping_policy'):
                    policies['shipping_profile_id'] = ebay_data.get('shipping_policy')
                if ebay_data.get('payment_policy'):
                    policies['payment_profile_id'] = ebay_data.get('payment_policy')
                if ebay_data.get('return_policy'):
                    policies['return_profile_id'] = ebay_data.get('return_policy')
            
            result = await ebay_service.create_listing_from_product(
                product=product,
                reverb_api_data=reverb_data,
                use_shipping_profile=True,
                **policies
            )
            
            if result.get('status') == 'success':
                return {'status': 'success', 'id': result.get('ItemID')}
            else:
                return {'status': 'error', 'message': result.get('message', 'Unknown error')}
                
        elif platform == 'shopify':
            shopify_service = ShopifyService(session, settings)
            result = await shopify_service.create_listing_from_product(product)
            
            if result.get('status') == 'success':
                return {'status': 'success', 'id': result.get('external_id')}
            else:
                return {'status': 'error', 'message': result.get('message', 'Unknown error')}
                
        elif platform == 'vr':
            vr_service = VRService(session, settings)
            result = await vr_service.create_listing_from_product(product)
            
            if result.get('status') == 'success':
                return {'status': 'success', 'id': result.get('external_id')}
            else:
                return {'status': 'error', 'message': result.get('message', 'Unknown error')}
                
    except Exception as e:
        logger.error(f"  Error retrying {platform}: {str(e)}")
        return {'status': 'error', 'message': str(e)}
    
    return {'status': 'error', 'message': f'Unknown platform: {platform}'}


async def process_partial_event(session: AsyncSession, event: SyncEvent) -> Dict:
    """Process a single partial/error event."""
    logger.info(f"\nProcessing event {event.id} (status: {event.status}, type: {event.change_type})")
    logger.info(f"  Platform: {event.platform_name}, External ID: {event.external_id}")
    
    # Only process new_listing events
    if event.change_type != 'new_listing':
        logger.info(f"  ⏭️ Skipping - not a new_listing event (type: {event.change_type})")
        return {'status': 'skipped', 'reason': 'Not a new_listing event'}
    
    # Get the product
    product = None
    if not event.product_id:
        logger.warning("  ⚠️ No product_id on event - attempting to find product by SKU")
        
        # Try to find product by Reverb external_id
        if event.platform_name == 'reverb' and event.external_id:
            sku = f"REV-{event.external_id}"
            logger.info(f"  🔍 Looking for product with SKU: {sku}")
            
            stmt = select(Product).where(Product.sku == sku)
            result = await session.execute(stmt)
            product = result.scalar_one_or_none()
            
            if product:
                logger.info(f"  ✅ Found product ID {product.id} by SKU lookup")
                # Update the event with the product_id
                event.product_id = product.id
                logger.info(f"  🔧 Updated event with product_id: {product.id}")
            else:
                logger.error(f"  ❌ No product found with SKU {sku}")
                return {'status': 'error', 'reason': f'Product not found for SKU {sku}'}
        else:
            logger.error("  ❌ Cannot determine product - not a Reverb event or no external_id")
            return {'status': 'error', 'reason': 'Cannot determine product without Reverb external_id'}
    else:
        product = await session.get(Product, event.product_id)
        if not product:
            logger.error(f"  ❌ Product ID {event.product_id} not found in database")
            return {'status': 'error', 'reason': f'Product ID {event.product_id} not found'}
    
    logger.info(f"  Product: {product.sku} - {product.brand} {product.model}")
    logger.info(f"  Price: £{product.base_price:,.0f}")
    
    # Parse the notes to see what was attempted
    notes = {}
    if event.notes:
        try:
            notes = json.loads(event.notes) if isinstance(event.notes, str) else event.notes
            logger.info("  📋 Event notes parsed successfully")
            logger.info(f"    Original results: {notes.get('results', {})}")
        except Exception as e:
            logger.warning(f"  ⚠️ Could not parse event notes: {e}")
            logger.info(f"    Raw notes: {event.notes}")
    else:
        logger.info("  📋 No notes found on event")
    
    results = notes.get('results', {})
    platforms_to_check = ['ebay', 'shopify', 'vr']
    logger.info(f"  🔍 Checking platforms: {platforms_to_check}")
    
    # Check current status of each platform
    actual_status = {}
    needs_retry = []
    
    logger.info("\n  === PLATFORM STATUS CHECK ===")
    for platform in platforms_to_check:
        logger.info(f"\n  Checking {platform.upper()}:")
        if platform in results:
            # Check if it failed originally
            original_result = results[platform]
            logger.info(f"    Original attempt result: {original_result}")
            
            if original_result is None or (isinstance(original_result, dict) and original_result.get('status') == 'error'):
                logger.info(f"    Original attempt FAILED - checking current status...")
                # Check if it exists now
                external_id = await check_platform_status(session, product.id, platform)
                if external_id:
                    logger.info(f"    ✅ {platform} now exists: {external_id} (was created manually?)")
                    actual_status[platform] = external_id
                else:
                    logger.info(f"    ❌ {platform} still missing - will retry")
                    needs_retry.append(platform)
            else:
                # It was successful originally
                actual_status[platform] = original_result
                logger.info(f"    ✓ {platform} already exists: {original_result}")
        else:
            logger.info(f"    ⚠️ {platform} was not attempted in original sync")
            # Check if it exists anyway
            external_id = await check_platform_status(session, product.id, platform)
            if external_id:
                logger.info(f"    ✅ {platform} exists: {external_id}")
                actual_status[platform] = external_id
            else:
                logger.info(f"    ❌ {platform} missing - will retry")
                needs_retry.append(platform)
    
    # Get Reverb data if we need to retry anything
    reverb_data = None
    if needs_retry:
        logger.info(f"\n  🔄 Need to retry platforms: {needs_retry}")
        if event.external_id:
            try:
                logger.info(f"  📥 Fetching Reverb data for listing {event.external_id}...")
                # Get settings for Reverb API key
                settings = get_settings()
                from app.services.reverb.client import ReverbClient
                reverb_client = ReverbClient(settings.REVERB_API_KEY)
                reverb_data = await reverb_client.get_listing_details(event.external_id)
                logger.info("  ✅ Reverb data fetched successfully")
            except Exception as e:
                logger.error(f"  ❌ Failed to fetch Reverb data: {e}")
        else:
            logger.warning("  ⚠️ No external_id on event - cannot fetch Reverb data")
    else:
        logger.info("\n  ✅ All platforms exist - no retries needed")
    
    # Retry failed platforms
    retry_results = {}
    if needs_retry:
        logger.info("\n  === RETRYING FAILED PLATFORMS ===")
        for platform in needs_retry:
            logger.info(f"\n  Retrying {platform.upper()}...")
            result = await retry_failed_platform(session, product, platform, reverb_data)
            retry_results[platform] = result
            if result['status'] == 'success':
                actual_status[platform] = result['id']
                logger.info(f"  ✅ Successfully created {platform}: {result['id']}")
            else:
                logger.error(f"  ❌ Failed to create {platform}: {result['message']}")
    
    # Update event status
    all_success = all(platform in actual_status for platform in platforms_to_check)
    
    logger.info("\n  === FINAL STATUS ===")
    logger.info(f"  Platforms with listings: {list(actual_status.keys())}")
    logger.info(f"  Missing platforms: {[p for p in platforms_to_check if p not in actual_status]}")
    
    if all_success:
        event.status = 'processed'
        event.processed_at = datetime.now(timezone.utc)
        logger.info("\n  🎉 All platforms successful - marking event as PROCESSED")
    else:
        failed_platforms = [p for p in platforms_to_check if p not in actual_status]
        logger.info(f"\n  ⚠️ Still PARTIAL - missing: {failed_platforms}")
        logger.info(f"  Event status remains: {event.status}")
    
    # Update notes with current status
    new_notes = {
        'results': actual_status,
        'retry_results': retry_results,
        'last_check': datetime.now(timezone.utc).isoformat(),
        'original_notes': notes
    }
    event.notes = json.dumps(new_notes)
    
    logger.info("\n  💾 Saving changes to database...")
    await session.commit()
    logger.info("  ✅ Changes saved")
    
    return {
        'event_id': event.id,
        'original_status': event.status,
        'new_status': 'processed' if all_success else 'partial',
        'platforms_fixed': list(retry_results.keys()),
        'platforms_still_missing': [p for p in platforms_to_check if p not in actual_status]
    }


async def main(dry_run: bool = False, limit: Optional[int] = None, event_id: Optional[int] = None):
    """Main function to process all partial/error events."""
    logger.info("=== RECONCILING PARTIAL/ERROR SYNC EVENTS ===")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    
    async with async_session() as session:
        if event_id:
            # Process specific event
            logger.info(f"Processing specific event ID: {event_id}")
            event = await session.get(SyncEvent, event_id)
            if not event:
                logger.error(f"Event {event_id} not found")
                return
            if event.status not in ['partial', 'error']:
                logger.warning(f"Event {event_id} has status '{event.status}' (not partial/error)")
            events = [event]
        else:
            # Find all partial/error new_listing events
            stmt = select(SyncEvent).where(
                and_(
                    SyncEvent.status.in_(['partial', 'error']),
                    SyncEvent.change_type == 'new_listing'
                )
            ).order_by(SyncEvent.detected_at.desc())
            
            if limit:
                stmt = stmt.limit(limit)
            
            result = await session.execute(stmt)
            events = result.scalars().all()
        
        logger.info(f"Found {len(events)} partial/error events to process")
        
        results = []
        for event in events:
            if dry_run:
                logger.info(f"\n[DRY RUN] Would process event {event.id}")
                # Just check status without making changes
                if event.product_id:
                    product = await session.get(Product, event.product_id)
                    if product:
                        for platform in ['ebay', 'shopify', 'vr']:
                            external_id = await check_platform_status(session, product.id, platform)
                            if external_id:
                                logger.info(f"  {platform} exists: {external_id}")
                            else:
                                logger.info(f"  {platform} missing")
            else:
                result = await process_partial_event(session, event)
                results.append(result)
        
        # Summary
        if not dry_run:
            logger.info("\n=== SUMMARY ===")
            if results:
                fixed_count = sum(1 for r in results if r.get('new_status') == 'processed')
                still_partial = sum(1 for r in results if r.get('new_status') == 'partial')
                error_count = sum(1 for r in results if r.get('status') == 'error')
                skipped_count = sum(1 for r in results if r.get('status') == 'skipped')
                
                logger.info(f"Fixed (now complete): {fixed_count}")
                logger.info(f"Still partial: {still_partial}")
                logger.info(f"Errors: {error_count}")
                logger.info(f"Skipped: {skipped_count}")
                logger.info(f"Total processed: {len(results)}")
                
                # Show details of still partial events
                if still_partial > 0:
                    logger.info("\nStill partial events:")
                    for r in results:
                        if r.get('new_status') == 'partial':
                            logger.info(f"  Event {r['event_id']}: Missing {r['platforms_still_missing']}")
            else:
                logger.info("No events were processed")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Reconcile partial/error sync events")
    parser.add_argument('--event-id', type=int, help='Process specific event ID')
    parser.add_argument('--dry-run', action='store_true', help='Check status without making changes')
    parser.add_argument('--limit', type=int, help='Limit number of events to process')
    
    args = parser.parse_args()
    
    asyncio.run(main(dry_run=args.dry_run, limit=args.limit, event_id=args.event_id))