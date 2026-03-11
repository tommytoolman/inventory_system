# scripts/fix_vr_price_anomalies.py
import sys
import os
import asyncio
import logging
from typing import Dict, List, Optional

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import async_session
from app.models.product import Product
from app.models.sync_event import SyncEvent
from app.services.vr_service import VRService
from sqlalchemy import select
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def fix_vr_price_anomalies(dry_run: bool = True, limit: Optional[int] = None):
    """
    Fix ALL pending V&R price anomalies by pushing the correct master prices TO V&R.
    
    Args:
        dry_run: If True, simulates without making changes
        limit: Optional limit on number of items to process
    """
    
    async with async_session() as db:
        # Fetch ALL pending V&R price events, regardless of sync_run
        stmt = select(SyncEvent).where(
            SyncEvent.platform_name == 'vr',
            SyncEvent.change_type == 'price',
            SyncEvent.status == 'pending'
        ).order_by(SyncEvent.detected_at)
        
        if limit:
            stmt = stmt.limit(limit)
        
        events = (await db.execute(stmt)).scalars().all()
        logging.info(f"Found {len(events)} pending V&R price anomalies to fix")
        
        if not events:
            logging.info("No pending anomalies found.")
            return {'success': 0, 'failed': 0, 'details': []}
        
        # Extract the data we need before processing
        events_data = []
        for event in events:
            product = await db.get(Product, event.product_id)
            if product:
                events_data.append({
                    'event_id': event.id,
                    'sync_run_id': str(event.sync_run_id),
                    'product_id': event.product_id,
                    'external_id': event.external_id,
                    'sku': product.sku,
                    'correct_price': float(event.change_data.get('old', 0)),
                    'vr_price': float(event.change_data.get('new', 0))
                })
            else:
                logging.warning(f"Product {event.product_id} not found for event {event.id}")
        
        # Commit to clear the session
        await db.commit()
        
        # Group by sync_run for reporting
        by_sync_run = {}
        for item in events_data:
            run_id = item['sync_run_id']
            if run_id not in by_sync_run:
                by_sync_run[run_id] = []
            by_sync_run[run_id].append(item)
        
        logging.info(f"Processing events from {len(by_sync_run)} sync run(s)")
        
        # Now process each item
        vr_service = VRService(db)
        results = {'success': 0, 'failed': 0, 'details': []}
        
        for item_data in events_data:
            try:
                logging.info(f"\nFixing anomaly for: {item_data['sku']}")
                logging.info(f"  Master price (correct): £{item_data['correct_price']:.2f}")
                logging.info(f"  V&R price (incorrect): £{item_data['vr_price']:.2f}")
                logging.info(f"  Correction needed: £{item_data['vr_price']:.2f} -> £{item_data['correct_price']:.2f}")
                
                if not dry_run:
                    # Push the correct price to V&R
                    success = await vr_service.update_listing_price(
                        external_id=item_data['external_id'],
                        new_price=item_data['correct_price']
                    )
                    
                    if success:
                        logging.info(f"  ✓ Successfully updated V&R listing {item_data['external_id']}")
                        
                        # Update the event status in a fresh query
                        update_stmt = select(SyncEvent).where(SyncEvent.id == item_data['event_id'])
                        event = (await db.execute(update_stmt)).scalar_one()
                        event.status = 'processed'
                        event.processed_at = datetime.now(timezone.utc)
                        event.notes = f"V&R price corrected from £{item_data['vr_price']:.2f} to £{item_data['correct_price']:.2f}"
                        await db.commit()
                        
                        results['success'] += 1
                    else:
                        logging.error(f"  ✗ Failed to update V&R listing {item_data['external_id']}")
                        results['failed'] += 1
                else:
                    logging.info(f"  [DRY RUN] Would update V&R listing {item_data['external_id']}")
                    results['success'] += 1
                
                results['details'].append(item_data)
                
            except Exception as e:
                logging.error(f"Error processing V&R listing {item_data['external_id']}: {e}")
                results['failed'] += 1
        
        if not dry_run:
            logging.info("\n✅ All changes completed")
        else:
            logging.info("\n🔍 DRY RUN - No changes made")
        
        # Print summary
        print("\n" + "="*60)
        print("V&R PRICE ANOMALY FIX SUMMARY")
        print("="*60)
        print(f"Total anomalies processed: {len(events_data)}")
        print(f"Anomalies fixed: {results['success']}")
        print(f"Failed: {results['failed']}")
        
        # Show by sync run
        if len(by_sync_run) > 1:
            print("\nBy sync run:")
            for run_id, items in by_sync_run.items():
                print(f"  {run_id[:8]}...: {len(items)} items")
        
        if results['details']:
            print("\nPrice Corrections:")
            print(f"{'SKU':<20} {'V&R ID':<10} {'Master':>10} {'V&R Wrong':>10} {'Diff':>10}")
            print("-"*70)
            for d in results['details']:
                diff = d['vr_price'] - d['correct_price']
                print(f"{d['sku']:<20} {d['external_id']:<10} £{d['correct_price']:>9.2f} "
                    f"£{d['vr_price']:>9.2f} £{diff:>+9.2f}")
        
        return results

async def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Fix V&R price anomalies by pushing master prices TO V&R'
    )
    parser.add_argument('--live', action='store_true', 
                       help='Execute changes (default is dry run)')
    parser.add_argument('--limit', type=int, 
                       help='Limit number of items to process')
    
    args = parser.parse_args()
    
    print("\n" + "="*60)
    print("V&R PRICE ANOMALY FIXER")
    print("="*60)
    print(f"Mode: {'LIVE - Will update V&R' if args.live else 'DRY RUN'}")
    print(f"Scope: Processing ALL pending V&R price anomalies")
    if args.limit:
        print(f"Limit: {args.limit} items")
    print("="*60)
    
    await fix_vr_price_anomalies(dry_run=not args.live, limit=args.limit)

if __name__ == "__main__":
    asyncio.run(main())