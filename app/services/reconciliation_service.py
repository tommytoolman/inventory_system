# app/services/reconciliation_service.py
"""
Common reconciliation service for processing sync events.
Used by both CLI script and web UI to avoid code duplication.
"""

import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sync_event import SyncEvent
from app.models.product import Product
from app.services.sync_services import SyncService, ReconciliationReport


async def process_reconciliation(
    db: AsyncSession,
    event_id: Optional[int] = None,
    sync_run_id: Optional[str] = None,
    sku: Optional[str] = None,
    event_type: str = 'all',
    dry_run: bool = False
) -> ReconciliationReport:
    """
    Common reconciliation logic for all interfaces.
    
    Args:
        db: Database session
        event_id: Specific event ID to process (used by web UI)
        sync_run_id: Sync run ID to process (used by CLI)
        sku: SKU to process all pending events for
        event_type: Type of events to process ('all', 'status_change', 'new_listing', etc.)
        dry_run: Whether to simulate the operation
        
    Returns:
        ReconciliationReport with results
    """
    # Initialize sync service
    sync_service = SyncService(db)
    
    # If event_id is provided, get the SKU from it
    if event_id and not sku:
        event = await db.get(SyncEvent, event_id)
        if event and event.product_id:
            product = await db.get(Product, event.product_id)
            if product:
                sku = product.sku
        
        # For status_change and removed_listing, we want coordinated processing
        if event and event.change_type == 'removed_listing':
            event_type = 'status_change'  # This will include removed_listing in the search
    
    # Generate sync_run_id if not provided
    if not sync_run_id:
        sync_run_id = str(uuid.uuid4())
    
    # Process using the sync service
    report = await sync_service.reconcile_sync_run(
        sync_run_id=sync_run_id,
        dry_run=dry_run,
        event_type=event_type,
        sku=sku
    )
    
    return report