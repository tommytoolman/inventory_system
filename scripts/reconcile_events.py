# scripts/reconcile_events.py
"""
Command-line tool to run the RIFF Reconciliation (Action) Phase.

This script acts as a manual trigger for the SyncService, which is the core engine
for processing pending events from the `sync_events` table. It allows you to
process specific types of events (or all of them) and can be run in either a
'dry run' mode for safe testing or a 'live' mode to execute real changes.

The main logic for handling events is contained within the SyncService. This
script's primary roles are to:
1. Parse user arguments from the command line.
2. Find the relevant sync runs that have pending events.
3. Call the SyncService to process those events.
4. Print the detailed report that the service returns.

Usage Examples:
--------------------------------------------------------------------------------
# Perform a DRY RUN to see what actions WOULD be taken for 'status_change' events
python scripts/reconcile_events.py --event-type status_change --dry-run

# Perform a DRY RUN for 'new_listing' events
python scripts/reconcile_events.py --event-type new_listing --dry-run

# Perform a DRY RUN for ALL pending event types
python scripts/reconcile_events.py --all --dry-run

# --- LIVE MODE (USE WITH CAUTION) ---
# Execute a LIVE run, making real API calls to end listings for 'status_change' events
python scripts/reconcile_events.py --event-type status_change --live
"""


import sys, os
import asyncio
import argparse
import logging
from typing import Set, Optional
from sqlalchemy import select, or_, cast
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import async_session
from app.models.sync_event import SyncEvent
from app.models.product import Product
from app.services.reconciliation_service import process_reconciliation 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def find_sync_runs_with_pending_events(db: AsyncSession, event_type: str, sku: Optional[str] = None) -> Set[str]:
    """Finds unique sync_run_ids that have pending events."""
    logging.info(f"Searching for sync runs with pending '{event_type}' events...")
    
    stmt = select(SyncEvent.sync_run_id).where(SyncEvent.status == 'pending').distinct()
    
    if event_type != 'all':
        stmt = stmt.where(SyncEvent.change_type == event_type)
    
    # This now ONLY searches for events already linked to a product if a SKU is provided.
    # It will NOT find the rogue Shopify event here. This is intentional.
    if sku:
        logging.info(f"Filtering for SKU: {sku} (on linked products)")
        stmt = stmt.join(Product, SyncEvent.product_id == Product.id).where(Product.sku.ilike(sku))
        
    result = await db.execute(stmt)
    sync_run_ids = {str(row[0]) for row in result.all()}
    
    if sync_run_ids:
        logging.info(f"✅ Found {len(sync_run_ids)} sync run(s) with matching pending events.")
    else:
        logging.warning(f"⚠️ No sync runs found with matching pending events for this SKU.")
        
    return sync_run_ids

async def main(args):
    """Main function to run the reconciliation and print a report."""
    
    async with async_session() as db:
        if args.sku:
            # When SKU is provided, process ALL pending events for that SKU
            logging.info(f"Processing events for specific SKU: {args.sku}")
            report = await process_reconciliation(
                db=db,
                sku=args.sku,
                event_type=args.event_type,
                dry_run=args.dry_run
            )
            report.print_summary()
        else:
            # Normal flow - find sync runs with pending events
            sync_run_ids_to_process = await find_sync_runs_with_pending_events(db, args.event_type, args.sku)
            
            if not sync_run_ids_to_process:
                logging.warning("No sync runs found with pending events.")
                return
            
            for sync_run_id in sync_run_ids_to_process:
                report = await process_reconciliation(
                    db=db,
                    sync_run_id=sync_run_id,
                    event_type=args.event_type,
                    dry_run=args.dry_run
                )
                report.print_summary()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the RIFF Reconciliation (Action) Phase.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    parser.add_argument(
        '--event-type', 
        choices=['new_listing', 'status_change', 'all'], 
        default='all',
        help="Specify which type of event to process. Default is 'all'."
    )
    
    # THIS IS THE MISSING ARGUMENT
    parser.add_argument(
        '--sku',
        help="Optional: Process only events for a specific product SKU."
    )
    
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('--dry-run', action='store_true', help="Simulate the run.")
    mode_group.add_argument('--live', action='store_false', dest='dry_run', help="Execute the run with LIVE API calls.")
    
    args = parser.parse_args()
    asyncio.run(main(args))