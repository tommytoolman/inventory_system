# app/services/sync_service.py
"""
Central service for synchronizing products across multiple platforms.

This service coordinates:
1. Stock level synchronization across platforms
2. Platform-specific listing creation/updates
3. Status tracking and error handling
4. Reconciliation of detected changes from all platforms.
"""

import asyncio
import logging

from typing import Dict, List, Any, Optional, Set, NamedTuple, Tuple, Union, Sequence
from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum
from sqlalchemy import select, text, update, cast, or_, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from difflib import SequenceMatcher

from app.models.product import Product, ProductCondition, ProductStatus
from app.models.platform_common import PlatformCommon
from app.models.sale import Sale
from app.models.reverb import ReverbListing
from app.models.ebay import EbayListing
from app.models.shopify import ShopifyListing
from app.models.vr import VRListing
from app.models.sync_event import SyncEvent
from app.core.enums import SyncStatus, ListingStatus
from app.services.sync_stats_service import SyncStatsService
from app.services.notification_service import EmailNotificationService
from app.core.events import StockUpdateEvent
from app.core.config import get_settings

from app.services.ebay_service import EbayService
from app.services.reverb_service import ReverbService
from app.services.shopify_service import ShopifyService
from app.services.vr_service import VRService
from app.services.vr_job_queue import enqueue_vr_job

# Note: logging.basicConfig removed - use app.core.logging_config instead
logger = logging.getLogger(__name__)


def _normalize_platform_status(platform: str, status: Optional[str]) -> Optional[str]:
    """Normalize raw platform status strings to internal `ListingStatus` values."""

    if status is None:
        return None

    normalized = str(status).strip().lower()
    if not normalized:
        return None

    platform = (platform or "").strip().lower()

    if platform == "ebay":
        if normalized in {"completed", "endedwithsales", "sold"}:
            return ListingStatus.SOLD.value
        if normalized == "ended":
            return ListingStatus.ENDED.value
        if normalized in {"active", "live"}:
            return ListingStatus.ACTIVE.value
        if normalized in {"inactive", "unsold"}:
            return ListingStatus.INACTIVE.value

    elif platform == "reverb":
        if normalized == "live":
            return ListingStatus.ACTIVE.value
        if normalized in {"sold", "ended"}:
            return normalized

    elif platform == "shopify":
        if normalized == "archived":
            return ListingStatus.SOLD.value

    elif platform == "vr":
        if normalized == "live":
            return ListingStatus.ACTIVE.value

    return normalized

# Add these data structures after your imports
@dataclass
class DetectedChange:
    """Represents a single detected change between platform and local data"""
    platform: str
    external_id: str
    product_id: Optional[int]  # None if product not found locally
    sku: str
    change_type: str  # "status_change", "price_change", "title_change", "new_listing", "removed_listing"
    field: str  # "status", "price", "title", etc.
    old_value: Any
    new_value: Any
    confidence: float = 1.0  # How confident we are this is a real change
    requires_propagation: bool = True  # Should this sync to other platforms?
    metadata: Optional[Dict[str, Any]] = None  # Extra context for UI/scripts

@dataclass
class SyncReport:
    """Summary report of sync operation"""
    platform: str
    timestamp: datetime
    total_platform_items: int
    total_local_items: int
    changes_detected: List[DetectedChange]
    errors: List[str]
    processing_time_seconds: float
    
    @property
    def changes_by_type(self) -> Dict[str, int]:
        """Group changes by type for summary"""
        counts = {}
        for change in self.changes_detected:
            counts[change.change_type] = counts.get(change.change_type, 0) + 1
        return counts

@dataclass
class ReconciliationReport:
    """A comprehensive report for a sync reconciliation run (the Action Phase)."""
    sync_run_id: str
    dry_run: bool
    summary: Dict[str, int]
    actions_taken: List[str]
    detected_changes: List[Dict]
    
    def print_summary(self):
        """Prints a formatted report to the console."""
        print("\n" + "="*50)
        print("RECONCILIATION REPORT")
        print("="*50)
        print(f"Sync Run ID: {self.sync_run_id}")
        print(f"Mode         : {'Dry Run' if self.dry_run else 'Live Run'}")
        
        summary = self.summary
        print("\n## Summary ##")
        print(f"- Events Processed : {summary.get('processed', 0)}")
        print(f"- Sale Events      : {summary.get('sales', 0)}")
        print(f"- Other Changes    : {summary.get('non_sale_changes', 0)}")
        print(f"- Actions Taken    : {summary.get('actions_taken', 0)}")
        print(f"- Errors           : {summary.get('errors', 0)}")
        
        if self.actions_taken:
            print("\n## Detailed Actions Log ##")
            for action in self.actions_taken:
                print(f"- {action}")
        else:
            print("\n## No Detailed Actions Were Taken ##")
        
        print("\n--- End of Report ---")

class SyncService:
    
    """Coordinates synchronization between inventory system and external platforms."""
    
    def __init__(self, db: AsyncSession, stock_manager=None, vr_executor=None):
        self.db = db
        self.stock_manager = stock_manager
        settings = get_settings()
        self.platform_services = {
            "reverb": ReverbService(db, settings),
            "shopify": ShopifyService(db, settings),
            "ebay": EbayService(db, settings),
            "vr": VRService(db),
        }
        self.email_service = EmailNotificationService(settings)
        self.vr_executor = vr_executor
        self._vr_semaphore = asyncio.Semaphore(1)
        self._background_tasks: Set[asyncio.Task] = set()

    async def _group_events_by_product(self, events: List[SyncEvent]) -> Dict[int, List[SyncEvent]]:
        """Group sync events by product_id for coordinated processing."""
        grouped = {}
        for event in events:
            if event.product_id:
                if event.product_id not in grouped:
                    grouped[event.product_id] = []
                grouped[event.product_id].append(event)
        return grouped

    async def _handle_coordinated_events(self, product_events: List[SyncEvent], summary: Dict, actions: List, dry_run: bool) -> bool:
        """
        Handle multiple related events for the same product as a coordinated action.
        
        Common patterns:
        - Reverb status_change (ended) + VR removed_listing = offline/private sale
        - Multiple platform status_change to sold/ended = item sold
        """
        logger.info(f"Handling {len(product_events)} coordinated events for product {product_events[0].product_id}")
        
        # Analyze the events to determine the action
        status_changes = [e for e in product_events if e.change_type == 'status_change']
        removed_listings = [e for e in product_events if e.change_type == 'removed_listing']
        
        # Get the product
        product = await self.db.get(Product, product_events[0].product_id)
        if not product:
            for event in product_events:
                event.notes = "Product not found in database"
                event.status = 'error'
            return False
        
        # Determine if this is a sale or just an ending
        is_sold = False
        sale_platform = None
        
        for sc in status_changes:
            change_data = sc.change_data or {}
            new_state = change_data.get('new')

            # Reverb is system-of-record: treat REVERB ended as a sale
            if sc.platform_name == 'reverb' and new_state in ('sold', 'ended'):
                is_sold = True
                sale_platform = 'reverb'
                break

            if new_state == 'sold' or change_data.get('is_sold'):
                is_sold = True
                sale_platform = sc.platform_name
                break

        # If not explicitly sold but we have ended + removed, treat as offline sale
        if not is_sold and status_changes and removed_listings:
            # Check if any status_change is to "ended"
            for sc in status_changes:
                change_data = sc.change_data or {}
                if change_data.get('new') == 'ended':
                    is_sold = True
                    sale_platform = sc.platform_name or 'offline'
                    break
        
        # Log the coordinated action
        action_desc = f"[COORDINATED] Product #{product.id} ({product.sku}): "
        if is_sold:
            action_desc += f"SOLD ({sale_platform})"
            summary["sales"] += 1
        else:
            action_desc += "ENDED/REMOVED"
            summary["non_sale_changes"] += 1
        
        action_desc += f" - Processing {len(product_events)} events across platforms: "
        platforms_summary = ", ".join([f"{e.platform_name}:{e.change_type}" for e in product_events])
        action_desc += platforms_summary
        
        if dry_run:
            action_desc += " (DRY RUN)"
        
        actions.append(action_desc)
        logger.info(action_desc)
        
        if not dry_run:
            try:
                # Update product status
                if is_sold:
                    if product.is_stocked_item and product.quantity > 0:
                        product.quantity -= 1
                        if product.quantity == 0:
                            product.status = ProductStatus.SOLD
                    else:
                        product.status = ProductStatus.SOLD
                else:
                    # No sale detected: treat as archive-level removal
                    product.status = ProductStatus.ARCHIVED
                
                self.db.add(product)
                
                # Update platform_common status for source platforms
                source_platforms = {e.platform_name for e in product_events}
                for event in product_events:
                    # Find the platform_common record
                    stmt = select(PlatformCommon).where(
                        PlatformCommon.product_id == product.id,
                        PlatformCommon.platform_name == event.platform_name
                    )
                    platform_link = (await self.db.execute(stmt)).scalar_one_or_none()
                    
                    if platform_link:
                        # For status_change events, mark as sold/ended
                        if event.change_type == 'status_change':
                            change_data = event.change_data or {}
                            if change_data.get('is_sold') or change_data.get('new') == 'sold':
                                platform_link.status = ListingStatus.SOLD.value
                            else:
                                platform_link.status = ListingStatus.ENDED.value
                        # For removed_listing events, mark as removed
                        elif event.change_type == 'removed_listing':
                            platform_link.status = ListingStatus.REMOVED.value
                        
                        self.db.add(platform_link)
                        logger.info(f"Updated {event.platform_name} platform_common status to {platform_link.status}")
                
                # Propagate ending to other platforms (respect stocked-item rules)
                platform_filter = self._get_end_listing_targets(product)
                if platform_filter == set():
                    success_platforms, action_log, failed_count = [], [], 0
                else:
                    success_platforms, action_log, failed_count = await self._propagate_end_listing(
                        product,
                        source_platforms,
                        dry_run,
                        platform_filter=platform_filter,
                    )
                
                actions.extend(action_log)
                
                # Update platform_common status for successfully propagated platforms
                if not dry_run and success_platforms:
                    for platform in success_platforms:
                        stmt = select(PlatformCommon).where(
                            PlatformCommon.product_id == product.id,
                            PlatformCommon.platform_name == platform
                        )
                        platform_link = (await self.db.execute(stmt)).scalar_one_or_none()
                        if platform_link:
                            # Mark as ended (propagated from sale elsewhere)
                            platform_link.status = ListingStatus.ENDED.value
                            self.db.add(platform_link)
                            logger.info(f"Updated {platform} platform_common status to ENDED (propagated)")
                
                # Update each event based on propagation success
                all_success = failed_count == 0
                for event in product_events:
                    if all_success:
                        event.status = 'processed'
                        event.processed_at = datetime.now(timezone.utc)
                        event.notes = f"Processed as coordinated {sale_platform if is_sold else 'ending'}"
                    else:
                        event.status = 'partial'
                        event.notes = f"Coordinated action partially failed. Failed platforms: {failed_count}"
                
                await self.db.commit()
                summary["actions_taken"] += len(product_events)
                return all_success
                
            except Exception as e:
                logger.error(f"Error in coordinated event handling: {e}", exc_info=True)
                await self.db.rollback()
                for event in product_events:
                    event.status = 'error'
                    event.notes = f"Error during coordinated processing: {str(e)}"
                summary["errors"] += len(product_events)
                return False
        else:
            # Dry run - mark all events as would be processed
            summary["actions_taken"] += len(product_events)
            return True

    async def _process_single_event(self, event: SyncEvent, summary: Dict, actions: List, dry_run: bool) -> bool:
        """Process a single event (extracted from the original for loop logic)."""
        success = False
        
        try:
            if event.change_type == 'status_change':
                success = await self._handle_status_change(event, summary, actions, dry_run)
            elif event.change_type == 'new_listing':
                success = await self._process_new_listing(event, summary, actions, dry_run)
            elif event.change_type in ['price_change', 'price']:
                success = await self._handle_price_change(event, summary, actions, dry_run)
            elif event.change_type == 'removed_listing':
                success = await self._handle_removed_listing(event, summary, actions, dry_run)
            elif event.change_type == 'quantity_change':
                success = await self._handle_quantity_change(event, summary, actions, dry_run)
            elif event.change_type == 'order_sale':
                success = await self._handle_order_sale(event, summary, actions, dry_run)

            if success:
                event.status = 'processed'
                event.processed_at = datetime.now(timezone.utc)
            else:
                event.status = 'error'
                summary["errors"] += 1
                
        except Exception as e:
            logger.error(f"Error processing event {event.id}: {e}", exc_info=True)
            event.status = 'error'
            event.notes = str(e)
            summary["errors"] += 1
            
        return success

    async def reconcile_sync_run(self, sync_run_id: str, dry_run: bool = True, event_type: str = 'all', sku: Optional[str] = None) -> ReconciliationReport:
            logger.info(f"Starting reconciliation for sync_run_id: {sync_run_id} (Dry Run: {dry_run}, Type: {event_type})")
            
            summary = {"processed": 0, "sales": 0, "non_sale_changes": 0, "actions_taken": 0, "errors": 0}
            actions = []
            detected_changes = []

            # Step 1: Fetch the initial, known events
            stmt = select(SyncEvent).where(
                SyncEvent.status == 'pending'
            ).order_by(SyncEvent.detected_at)
            
            # If SKU is provided, get ALL pending events for that product regardless of sync_run_id
            if sku:
                stmt = stmt.join(Product, SyncEvent.product_id == Product.id).where(Product.sku.ilike(sku))
                logger.info(f"Searching for ALL pending events for SKU: {sku}")
            else:
                # Otherwise, filter by sync_run_id as usual
                stmt = stmt.where(SyncEvent.sync_run_id == sync_run_id)

            if event_type != 'all':
                # For coordinated processing, include both status_change and removed_listing
                if event_type == 'status_change':
                    stmt = stmt.where(or_(
                        SyncEvent.change_type == 'status_change',
                        SyncEvent.change_type == 'removed_listing'
                    ))
                else:
                    stmt = stmt.where(SyncEvent.change_type == event_type)
            
            initial_events = (await self.db.execute(stmt)).scalars().all()
            
            # Step 2: Search for rogue new_listing events
            rogue_events = []
            # Skip rogue search when SKU is provided (we already got ALL events for that SKU)
            if sku and event_type == 'new_listing':
                logger.info(f"Searching for unlinked 'new_listing' events matching SKU: {sku}")
                
                # --- THIS IS THE FINAL CORRECTED QUERY ---
                change_data_as_jsonb = cast(SyncEvent.change_data, JSONB)
                
                # Build the path to the SKU using standard index operators
                shopify_sku_path = change_data_as_jsonb['raw_data']['variants']['nodes'][0]['sku']
                
                # Convert the final JSON value to a string for comparison
                shopify_sku_as_text = shopify_sku_path.as_string()

                rogue_stmt = select(SyncEvent).where(
                    SyncEvent.sync_run_id == sync_run_id,
                    SyncEvent.status == 'pending',
                    SyncEvent.product_id == None,
                    SyncEvent.change_type == 'new_listing',
                    or_(
                        change_data_as_jsonb.op('->>')('sku').ilike(sku),
                        shopify_sku_as_text.ilike(sku)
                    )
                )
                # --- END OF QUERY CORRECTION ---

                rogue_events = (await self.db.execute(rogue_stmt)).scalars().all()
                if rogue_events:
                    logger.info(f"Found {len(rogue_events)} additional rogue listing event(s).")

            # Combine and de-duplicate the event lists
            all_events_dict = {event.id: event for event in initial_events}
            all_events_dict.update({event.id: event for event in rogue_events})
            events = sorted(all_events_dict.values(), key=lambda e: e.detected_at)

            logger.info(f"Found {len(events)} total pending events to reconcile.")
            
            # Check for products with partially processed events
            if event_type == 'status_change' and events:
                # Get all product_ids from pending events
                product_ids = {e.product_id for e in events if e.product_id}
                
                if product_ids:
                    # Look for any other pending events for these products
                    logger.info(f"Checking for additional pending events for {len(product_ids)} products...")
                    
                    additional_stmt = select(SyncEvent).where(
                        SyncEvent.product_id.in_(product_ids),
                        SyncEvent.status == 'pending',
                        SyncEvent.id.notin_([e.id for e in events])  # Exclude already found events
                    )
                    
                    additional_events = (await self.db.execute(additional_stmt)).scalars().all()
                    if additional_events:
                        logger.info(f"Found {len(additional_events)} additional pending events for the same products")
                        events.extend(additional_events)
                        events = sorted(events, key=lambda e: e.detected_at)
            
            # Group events by product for coordinated processing
            grouped_events = await self._group_events_by_product(events)
            
            # Also collect events without product_id for individual processing
            orphan_events = [e for e in events if not e.product_id]
            
            # Process coordinated events first
            for product_id, product_events in grouped_events.items():
                # Check if we should process these together
                event_types = {e.change_type for e in product_events}
                
                if len(product_events) > 1 and ('status_change' in event_types or 'removed_listing' in event_types):
                    # Multiple events for same product - process together
                    success = await self._handle_coordinated_events(product_events, summary, actions, dry_run)
                    summary["processed"] += len(product_events)
                    for event in product_events:
                        detected_changes.append(event.change_data)
                else:
                    # Single event - process individually
                    for event in product_events:
                        detected_changes.append(event.change_data)
                        success = await self._process_single_event(event, summary, actions, dry_run)
                        summary["processed"] += 1
            
            # Process orphan events individually
            for event in orphan_events:
                detected_changes.append(event.change_data)
                success = await self._process_single_event(event, summary, actions, dry_run)
                summary["processed"] += 1

            if not dry_run:
                await self.db.commit()
                logger.info("LIVE RUN: Database changes were committed.")
                
                # Update sync stats silently
                try:
                    stats_service = SyncStatsService(self.db)
                    await stats_service.update_stats(
                        summary=summary,
                        sync_run_id=sync_run_id
                    )
                except Exception as e:
                    logger.error(f"Failed to update sync stats: {e}")
                    # Don't fail the whole operation if stats update fails
            else:
                logger.info("DRY RUN: Database changes were rolled back.")
                await self.db.rollback()

            logger.info(f"Reconciliation complete. Summary: {summary}")
            return ReconciliationReport(
                sync_run_id=sync_run_id, 
                dry_run=dry_run, 
                summary=summary, 
                actions_taken=actions, 
                detected_changes=detected_changes
            )

    async def _handle_new_listing(self, event: SyncEvent, summary: Dict, actions: List, dry_run: bool) -> bool:
        logger.info(f"Handling 'new_listing' event for {event.platform_name} item {event.external_id}")
        
        # NEW CODE - For Reverb new_listings, construct SKU from external_id
        # This gives us REV-xxxxx format for Reverb-sourced products
        if event.platform_name == 'reverb':
            sku = f"REV-{event.external_id}"
            logger.info(f"Using Reverb external_id as SKU: {sku}")
        else:
            # For other platforms, still try to get from change_data
            change_data = event.change_data or {}
            sku = change_data.get('sku')
            # Handle case where SKU might be nested (for Shopify)
            if not sku and 'raw_data' in change_data:
                try:
                    sku = change_data['raw_data']['variants']['nodes'][0]['sku']
                except (KeyError, IndexError):
                    pass # SKU remains None if path doesn't exist
            
            if not sku:
                event.status = 'error'
                event.notes = "New listing event is missing SKU in change_data. Cannot process."
                summary['errors'] += 1
                return False

        # Find the master product using a case-insensitive lookup
        product_stmt = select(Product).where(Product.sku.ilike(sku))
        product = (await self.db.execute(product_stmt)).scalar_one_or_none()
        
        # --- NEW STATE-AWARE LOGIC ---
        if product and product.status == ProductStatus.SOLD:
            logger.warning(f"Rogue active listing {event.platform_name} ID {event.external_id} found for a product that is already SOLD (Product #{product.id}).")
            
            # --- GET OR CREATE LOGIC ---
            # First, try to find an existing link for this rogue listing.
            stmt = select(PlatformCommon).where(
                PlatformCommon.platform_name == event.platform_name,
                PlatformCommon.external_id == event.external_id
            )
            platform_common = (await self.db.execute(stmt)).scalar_one_or_none()
            
            if not platform_common:
                # If it doesn't exist, create it.
                logger.info(f"Creating new platform_common link for rogue {event.platform_name} listing.")
                platform_common = PlatformCommon(
                    product_id=product.id,
                    platform_name=event.platform_name,
                    external_id=event.external_id,
                    status=ListingStatus.ACTIVE, # It's currently active on the platform
                    sync_status=SyncStatus.PENDING 
                )
                self.db.add(platform_common)
                await self.db.flush() # Ensure it's in the session before ending
            else:
                logger.info(f"Found existing platform_common link for rogue {event.platform_name} listing.")
            # --- END GET OR CREATE LOGIC ---
            
            # Directly end the rogue listing on its own platform
            action_desc = f"[DRY RUN][ACTION] Rogue listing on {event.platform_name.upper()} for sold Product #{product.id}. Would end listing."
            action_was_successful = True # Assume success for dry run

            if not dry_run:
                service = self.platform_services.get(event.platform_name)
                if service and hasattr(service, 'mark_item_as_sold'):
                    success = await service.mark_item_as_sold(event.external_id)
                    if success:
                        # --- THIS BLOCK WAS MISSING ---
                        platform_common.status = ListingStatus.ENDED.value
                        platform_common.sync_status = SyncStatus.SYNCED.value
                        self.db.add(platform_common)
                        # --- END MISSING BLOCK ---
                        action_desc = f"[SUCCESS] Rogue listing on {event.platform_name.upper()} for sold Product #{product.id} -> Listing ended successfully."
                    else:
                        action_was_successful = False
                        action_desc = f"[ERROR] Rogue listing on {event.platform_name.upper()} for sold Product #{product.id} -> FAILED to end."
                else:
                    action_was_successful = False
                    action_desc = f"[ERROR] No service available to end listing on {event.platform_name.upper()}."

            actions.append(action_desc)
            summary['actions_taken'] += 1
            event.notes = f"Rogue listing for sold product #{product.id} processed. End action triggered."
            # The boolean return now signals success/failure to the main loop
            return action_was_successful
        
        # --- ORIGINAL LOGIC (for when product is active or doesn't exist yet) ---
        if event.platform_name != 'reverb':
            event.status = 'needs_review'
            event.notes = f"Automated creation from {event.platform_name} not supported yet."
            return False

        reverb_service = self.platform_services['reverb']
        try:
            details = await reverb_service.client.get_listing_details(event.external_id)
        except Exception as e:
            event.status, event.notes = 'error', f"Failed to fetch source details from Reverb API: {e}"
            summary['errors'] += 1
            return False
        
        # This will use the existing product if found (and not sold), or create a new one.
        master_product = product
        if not master_product:
            try:
                master_product = Product(
                    sku=sku, brand=details.get('make'), model=details.get('model'),
                    description=details.get('description'), base_price=float(details.get('price', {}).get('amount', 0)),
                    condition=ProductCondition.GOOD, status=ProductStatus.ACTIVE)
                self.db.add(master_product)
                await self.db.flush()
            except Exception as e:
                event.status, event.notes = 'error', f"Failed to create master product in database: {e}"
                summary['errors'] += 1
                return False
        else:
            logger.warning(f"Product with SKU {sku} already exists (ID: {master_product.id}). Will link instead of creating a duplicate.")

        # Update the event with the product_id
        event.product_id = master_product.id
        logger.info(f"Updated event {event.id} with product_id: {master_product.id}")

        source_platform_common = PlatformCommon(
            product_id=master_product.id, platform_name='reverb', external_id=event.external_id,
            status=ListingStatus.ACTIVE, sync_status=SyncStatus.SYNCED)
        self.db.add(source_platform_common)
        
        platforms_to_create_on = ['shopify', 'ebay', 'vr']
        for platform in platforms_to_create_on:
            service = self.platform_services.get(platform)
            if service and hasattr(service, 'create_listing_from_product'):
                action_desc = f"[ACTION] New item #{master_product.id} from Reverb. Creating listing on {platform.upper()}."
                if dry_run:
                    action_desc += " (DRY RUN)"
                else:
                    try:
                        if platform == 'ebay':
                            logger.info("=== EBAY LISTING CREATION FROM SYNC SERVICE ===")
                            logger.info(f"Product: {master_product.sku} - {master_product.brand} {master_product.model}")
                            
                            # Get policies - matching what inventory route does
                            policies = {
                                'shipping_profile_id': '252277357017',  # Default shipping profile (corrected)
                                'payment_profile_id': '252544577017',   # Default payment profile (corrected)
                                'return_profile_id': '252277356017'     # Default return profile
                            }
                            
                            # Check if product has specific eBay policies in platform_data
                            if hasattr(master_product, 'platform_data') and master_product.platform_data and 'ebay' in master_product.platform_data:
                                ebay_data = master_product.platform_data['ebay']
                                logger.info(f"Found eBay platform data: {ebay_data}")
                                # Override with product-specific policies if they exist
                                if ebay_data.get('shipping_policy'):
                                    policies['shipping_profile_id'] = ebay_data.get('shipping_policy')
                                    logger.info(f"Using product-specific shipping policy: {policies['shipping_profile_id']}")
                                if ebay_data.get('payment_policy'):
                                    policies['payment_profile_id'] = ebay_data.get('payment_policy')
                                    logger.info(f"Using product-specific payment policy: {policies['payment_profile_id']}")
                                if ebay_data.get('return_policy'):
                                    policies['return_profile_id'] = ebay_data.get('return_policy')
                                    logger.info(f"Using product-specific return policy: {policies['return_profile_id']}")
                            else:
                                logger.info("No product-specific eBay policies found, using defaults")
                            
                            logger.info(f"Final eBay policies to use: {policies}")
                            logger.info(f"use_shipping_profile=True (Business Policies mode)")
                            
                            # Pass Reverb API data as reverb_api_data parameter
                            result = await service.create_listing_from_product(
                                product=master_product,
                                reverb_api_data=details,
                                use_shipping_profile=True,  # Use Business Policies like inventory route
                                **policies  # Pass the policies like inventory route does
                            )
                        elif platform == 'shopify':
                            result = await service.create_listing_from_product(
                                master_product,
                                details,
                            )
                        elif platform == 'vr':
                            job = await enqueue_vr_job(
                                self.db,
                                product_id=master_product.id,
                                payload={
                                    "sync_source": "sync_service",
                                    "reverb_data": details or {},
                                },
                            )
                            await self.db.commit()
                            logger.info("Queued V&R job %s for product %s via sync service", job.id, master_product.sku)
                            result = {
                                "status": "success",
                                "queued": True,
                                "job_id": job.id,
                            }
                        else:
                            result = await service.create_listing_from_product(master_product)
                        
                        if result.get('status') == 'success':
                            action_desc += f" -> SUCCESS (New ID: {result.get('external_id')})"
                        else:
                            action_desc += f" -> FAILED: {result.get('message')}"
                            summary['errors'] += 1
                    except Exception as e:
                        action_desc += f" -> FAILED: {e}"
                        summary['errors'] += 1
                actions.append(action_desc)
                summary['actions_taken'] += 1
        
        event.notes = f"Processed new master product #{master_product.id}."
        return True

    async def _handle_status_change(self, event: SyncEvent, summary: Dict, actions: List, dry_run: bool) -> bool:
        """
        Handles a 'status_change' event, differentiating between sales and other changes.
        This version ensures propagation/consistency and updates both manager and specialist tables.
        """
        if not event.product_id:
            event.notes = "Event is missing product_id, cannot process status change."
            return False

        product = await self.db.get(Product, event.product_id)
        if not product:
            event.notes = f"Product with ID {event.product_id} not found."
            return False

        # Determine the EXACT new status ('sold' or 'ended') from the event data.
        is_sale_signal = self._is_sale_event(event.platform_name, event.change_data)
        raw_new_status = event.change_data.get('new') if event.change_data else None
        new_status = _normalize_platform_status(event.platform_name, raw_new_status) or ListingStatus.ENDED.value

        # Gather platform metadata for email/reporting context.
        platform_common = await self._get_platform_common(product.id, event.platform_name)
        platform_common_id = platform_common.id if platform_common else None
        listing_url = platform_common.listing_url if platform_common else None

        # This handler should only process sale/ended signals.
        if not is_sale_signal:
            logger.info(
                "Status change for product %s on %s treated as non-sale (new_status=%s, raw=%s)",
                event.product_id,
                event.platform_name,
                new_status,
                raw_new_status,
            )
            event.notes = f"Acknowledged non-sale status change '{new_status}' with no action."
            return True

        # Update the master product based on whether it's a stocked item
        sale_alert_needed = False
        sale_platform = event.platform_name
        sale_price = event.change_data.get('sale_price') if event.change_data else None
        try:
            sale_price = float(sale_price) if sale_price is not None else None
        except (TypeError, ValueError):
            sale_price = None

        if sale_price is None and platform_common_id:
            sale_price = await self._derive_sale_price_from_listing(event.platform_name, platform_common_id)
        external_reference = event.external_id

        if product.is_stocked_item:
            # For stocked items, decrement quantity
            if product.quantity > 0:
                product.quantity -= 1
                self.db.add(product)
                logger.info(f"Sale signal from {event.platform_name}. Decremented quantity for stocked Product #{product.id}. New quantity: {product.quantity}")

                # Mark as SOLD only when quantity reaches 0
                if product.quantity == 0:
                    product.status = ProductStatus.SOLD
                    logger.info(f"Stocked Product #{product.id} quantity reached 0. Marking as SOLD.")
                    summary['sales'] += 1
                    sale_alert_needed = True
            else:
                logger.warning(f"Stocked Product #{product.id} already at 0 quantity. Received redundant signal from {event.platform_name}.")
        else:
            # For non-stocked items (one-off items), mark as SOLD immediately
            if product.status != ProductStatus.SOLD:
                summary['sales'] += 1
                product.status = ProductStatus.SOLD
                self.db.add(product)
                logger.info(f"First sale signal from {event.platform_name}. Marking one-off Product #{product.id} as SOLD.")
                sale_alert_needed = True
            else:
                logger.info(f"Product #{product.id} is already SOLD. Received redundant signal from {event.platform_name}. Verifying consistency...")

        # Perform the TWO-STAGE local update for the source platform of the event.
        logger.info(
            "Applying primary status update for product %s on %s -> %s",
            product.id,
            event.platform_name,
            new_status,
        )
        await self._update_local_platform_status(
            product_id=product.id,
            platform_name=event.platform_name,
            new_status=new_status
        )

        # Propagate the change to other active platforms.
        # For non-stocked items: always propagate when sold
        # For stocked items: only propagate when quantity reaches 0
        platform_filter = self._get_end_listing_targets(product)
        if platform_filter == set():
            should_propagate = False
        else:
            should_propagate = True if (platform_filter is None or platform_filter) else False

        propagated_platforms: List[str] = []

        if should_propagate:
            logger.info(
                "Propagating end signal from %s across other platforms (targets=%s) for product %s",
                event.platform_name,
                platform_filter if platform_filter is not None else "ALL",
                product.id,
            )
            successful_platforms, action_log, failed_count = await self._propagate_end_listing(
                product,
                event.platform_name,
                dry_run,
                platform_filter=platform_filter,
            )
            actions.extend(action_log)
            summary['actions_taken'] += len(action_log)
            propagated_platforms = successful_platforms.copy()

            if not dry_run and successful_platforms:
                logger.info(f"Updating local status for successfully ended platforms: {successful_platforms}")
                for platform in successful_platforms:
                    logger.info(
                        "Applying propagated status update for product %s on %s -> %s",
                        product.id,
                        platform,
                        ListingStatus.ENDED.value,
                    )
                    # Perform the two-stage update for each propagated platform.
                    await self._update_local_platform_status(
                        product_id=product.id,
                        platform_name=platform,
                        new_status=ListingStatus.ENDED.value # When propagating, 'ended' is the correct universal status.
                    )
            
            if failed_count > 0:
                event.notes = f"Consistency check failed to end listings on {failed_count} platform(s)."
                return False

        if sale_alert_needed and not dry_run:
            sale_status_label = self._describe_sale_status(event.platform_name, new_status)
            detected_at_str = None
            if event.detected_at:
                dt = event.detected_at
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)
                detected_at_str = dt.strftime("%Y-%m-%d %H:%M:%S %Z")

            await self._send_sale_alert(
                product,
                sale_platform,
                sale_price=sale_price,
                external_reference=external_reference,
                sale_status=sale_status_label,
                listing_url=listing_url,
                detected_at=detected_at_str,
                propagated_platforms=propagated_platforms,
            )

        if not dry_run:
            await self._record_sale_entry(
                product=product,
                platform_common=platform_common,
                event=event,
                status=new_status,
                sale_price=sale_price,
            )

        event.notes = "Sale signal processed and platform consistency enforced."
        return True   

    async def _record_sale_entry(
        self,
        *,
        product: Product,
        platform_common: Optional[PlatformCommon],
        event: SyncEvent,
        status: str,
        sale_price: Optional[float],
    ) -> None:
        """Persist a sale/ended event into the sales table."""

        platform_common = platform_common or await self._get_platform_common(product.id, event.platform_name)
        if not platform_common:
            logger.warning(
                "Skipping sale record for product %s on %s: no platform_common found",
                product.id,
                event.platform_name,
            )
            return

        external_id = event.external_id or platform_common.external_id
        if not external_id:
            logger.warning(
                "Skipping sale record for product %s on %s: missing external_id",
                product.id,
                event.platform_name,
            )
            return

        sale_date = event.detected_at or datetime.utcnow()
        if sale_date.tzinfo is not None:
            sale_date = sale_date.astimezone(timezone.utc).replace(tzinfo=None)

        existing_stmt = (
            select(Sale)
            .where(Sale.platform_listing_id == platform_common.id)
            .where(Sale.status == status)
        )
        existing = (await self.db.execute(existing_stmt)).scalar_one_or_none()

        payload = event.change_data or {}

        if existing:
            existing.sale_date = sale_date
            existing.sale_price = sale_price if sale_price is not None else existing.sale_price
            existing.original_list_price = existing.original_list_price or product.base_price
            existing.platform_data = {**(existing.platform_data or {}), **payload}
            existing.order_reference = existing.order_reference or payload.get("order_reference")
            existing.platform_external_id = external_id
            existing.buyer_location = existing.buyer_location or payload.get("buyer_location")
            self.db.add(existing)
            logger.info(
                "Updated existing sale record for product %s on %s",
                product.id,
                event.platform_name,
            )
            return

        sale_entry = Sale(
            product_id=product.id,
            platform_listing_id=platform_common.id,
            platform_name=event.platform_name,
            platform_external_id=external_id,
            status=status,
            sale_date=sale_date,
            sale_price=sale_price,
            original_list_price=product.base_price,
            order_reference=payload.get("order_reference"),
            buyer_location=payload.get("buyer_location"),
            platform_data=payload,
        )

        self.db.add(sale_entry)
        logger.info(
            "Recorded sale entry for product %s on %s (external_id=%s)",
            product.id,
            event.platform_name,
            external_id,
        )

    async def _send_sale_alert(
        self,
        product: Product,
        platform: str,
        *,
        sale_price: Optional[float],
        external_reference: Optional[str],
        sale_status: Optional[str],
        listing_url: Optional[str],
        detected_at: Optional[str],
        propagated_platforms: Optional[Sequence[str]],
    ) -> None:
        if not getattr(self, "email_service", None):
            return

        try:
            await self.email_service.send_sale_alert(
                product=product,
                platform=platform,
                sale_price=sale_price,
                external_id=external_reference,
                sale_status=sale_status,
                listing_url=listing_url,
                detected_at=detected_at,
                propagated_platforms=propagated_platforms,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to queue sale alert email for product %s: %s", product.id, exc, exc_info=True)

    async def _handle_price_change_old(self, event: SyncEvent, summary: Dict, actions: List, dry_run: bool):
        """Handles a 'price_change' event by updating the master product and propagating the change."""
        logger.info(f"Handling 'price_change' event for {event.platform_name} item {event.external_id}")
        
        if not event.product_id:
            event.notes = "Event is missing product_id, cannot process price change."
            summary["errors"] += 1
            return

        product = await self.db.get(Product, event.product_id)
        if not product:
            event.notes = f"Product with ID {event.product_id} not found."
            summary["errors"] += 1
            return

        try:
            new_price = float(event.change_data.get('new', 0.0))
            old_price = float(product.base_price)

            # Step 1: Update the Master Product's base_price
            product.base_price = new_price
            self.db.add(product)
            
            action_desc = f"Updated master price for Product #{product.id} (SKU: {product.sku}) from £{old_price} to £{new_price}."
            actions.append(action_desc)
            logger.info(action_desc)

            # Auto propagate is currently disabled to avoid unintended price changes. Review later.
            # Step 2: Propagate the price change to other active platforms
            # successful_platforms, action_log, failed_count = await self._propagate_price_update(product, event.platform_name, new_price, dry_run)
            # actions.extend(action_log)

            # if failed_count > 0:
            #     summary["errors"] += failed_count
            #     event.notes = f"Failed to propagate price update to {failed_count} platform(s)."
            
            # summary["actions_taken"] += 1 + len(action_log)
            summary["actions_taken"] += 1

        except (ValueError, TypeError) as e:
            logger.error(f"Could not parse price from event data: {event.change_data}. Error: {e}")
            event.notes = f"Invalid price data in event: {e}"
            summary["errors"] += 1

    async def _handle_price_change(self, event: SyncEvent, summary: Dict, actions: List, dry_run: bool):
        """
        Handles a 'price_change' event by updating the specialist table to log the anomaly for review.
        This does NOT change the master product.base_price.
        """
        logger.info(f"Handling 'price_change' event for {event.platform_name} item {event.external_id}")

        if not event.product_id or not event.platform_common_id:
            event.notes = "Event is missing product_id or platform_common_id, cannot log price anomaly."
            summary["errors"] += 1
            return False

        specialist_tables = {
            "reverb": {"table": ReverbListing, "price_col": "price_display"},
            "ebay": {"table": EbayListing, "price_col": "price"},
            "shopify": {"table": ShopifyListing, "price_col": "price"},
            "vr": {"table": VRListing, "price_col": "price_notax"}
        }

        platform_config = specialist_tables.get(event.platform_name)
        if not platform_config:
            event.notes = f"No specialist table configuration for platform: {event.platform_name}"
            summary["errors"] += 1
            return False

        try:
            new_price = float(event.change_data.get('new', 0.0))
            
            # Construct a dynamic SQLAlchemy update statement
            stmt = (
                update(platform_config["table"])
                .where(getattr(platform_config["table"], 'platform_id') == event.platform_common_id)
                .values({platform_config["price_col"]: new_price})
            )
            
            if not dry_run:
                await self.db.execute(stmt)

            action_desc = f"Logged price anomaly for {event.platform_name.upper()} Product #{event.product_id}. Specialist table price set to £{new_price} for review."
            actions.append(action_desc)
            logger.info(action_desc)
            summary["actions_taken"] += 1
            return True

        except (ValueError, TypeError) as e:
            logger.error(f"Could not parse price from event data: {event.change_data}. Error: {e}")
            event.notes = f"Invalid price data in event: {e}"
            summary["errors"] += 1
            return False

    async def _handle_removed_listing(self, event: SyncEvent, summary: Dict, actions: List, dry_run: bool) -> bool:
        """Handles a 'removed_listing' event by updating the local status."""
        logger.info(f"Handling 'removed_listing' event for {event.platform_name} item {event.external_id}")
        
        if not event.product_id:
            event.notes = f"Event {event.id} is missing product_id, cannot process removed_listing."
            return False

        product = await self._get_product(event.product_id)

        if (
            event.platform_name == "vr"
            and product
            and product.is_stocked_item
            and (product.quantity or 0) > 0
        ):
            remaining_qty = int(product.quantity or 0)
            action_desc = (
                f"Detected VR removal for stocked product #{product.id} (qty remaining: {remaining_qty})."
            )
            service = self.platform_services.get("vr")
            if service and hasattr(service, "create_listing_from_product"):
                if dry_run:
                    event.notes = (
                        "DRY RUN: would relist VR listing after sale while stock remains."
                    )
                    actions.append(
                        f"{action_desc} DRY RUN: would relist on VR instead of ending."
                    )
                    summary["actions_taken"] += 1
                    return True
                else:
                    try:
                        result = await service.create_listing_from_product(product)
                        if result.get("status") == "success":
                            new_id = result.get("external_id")
                            event.notes = (
                                f"Relisted on VR with new ID {new_id} after sale while stock remains."
                            )
                            actions.append(
                                f"{action_desc} Relisted on VR (new ID: {new_id})."
                            )
                            summary["actions_taken"] += 1
                            return True
                        else:
                            message = result.get("message") or "Unknown error"
                            event.notes = (
                                f"Attempted to relist on VR but received failure: {message}"
                            )
                            summary["errors"] += 1
                            return False
                    except Exception as exc:  # noqa: BLE001
                        logger.error(
                            "Failed to relist VR product %s after removal: %s",
                            product.id,
                            exc,
                            exc_info=True,
                        )
                        event.notes = f"Error relisting VR listing: {exc}"
                        summary["errors"] += 1
                        return False
            else:
                event.notes = (
                    "VR service unavailable; manual relist required for stocked item."
                )
                actions.append(
                    f"{action_desc} Unable to auto-relist because VR service is unavailable."
                )
                summary["actions_taken"] += 1
                return True
            return True

        # Find the corresponding platform_common record
        stmt = select(PlatformCommon).where(
            PlatformCommon.product_id == event.product_id,
            PlatformCommon.platform_name == event.platform_name
        )
        platform_link = (await self.db.execute(stmt)).scalar_one_or_none()

        if platform_link:
            # CHANGE 1: Use the correct status
            platform_link.status = ListingStatus.REMOVED.value
            platform_link.sync_status = SyncStatus.SYNCED.value
            self.db.add(platform_link)
            
            # Log a more specific message that includes the new status
            log_message = f"Updated platform_common for {event.platform_name} (Product #{event.product_id}) to status '{ListingStatus.REMOVED.value}'."
            logger.info(log_message)
            
            # CHANGE 2: Add a user-friendly message to the report's action log
            action_desc = f"Acknowledged listing removed from {event.platform_name.upper()} and updated local status to REMOVED for Product #{event.product_id}."
            actions.append(action_desc)
            summary["actions_taken"] += 1
            
            event.notes = "Acknowledged removed listing from platform and updated local status."
            return True
        else:
            event.notes = f"Could not find matching platform_common record to mark as removed."
            return False
    
    def _get_end_listing_targets(self, product: Product) -> Optional[Set[str]]:
        """Return which platforms should be ended when stock hits zero.

        None => end all active platforms (used for one-off items).
        Empty set => do not end anything.
        Non-empty set => end only the specified platforms.
        """
        if not product.is_stocked_item:
            return None

        if product.quantity == 0:
            return {"vr"}

        return set()

    async def _get_product(self, product_id: int) -> Optional[Product]:
        stmt = select(Product).where(Product.id == product_id)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def _get_platform_common(self, product_id: int, platform_name: str) -> Optional[PlatformCommon]:
        stmt = (
            select(PlatformCommon)
            .where(PlatformCommon.product_id == product_id)
            .where(PlatformCommon.platform_name == platform_name)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def _derive_sale_price_from_listing(self, platform_name: str, platform_common_id: Optional[int]) -> Optional[float]:
        if not platform_common_id:
            return None

        price_sources = {
            'reverb': (ReverbListing, ReverbListing.list_price),
            'ebay': (EbayListing, EbayListing.price),
            'shopify': (ShopifyListing, ShopifyListing.price),
            'vr': (VRListing, VRListing.price_notax),
        }

        config = price_sources.get(platform_name)
        if not config:
            return None

        table, column = config
        stmt = select(column).where(table.platform_id == platform_common_id)
        value = (await self.db.execute(stmt)).scalar_one_or_none()

        if value is None:
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _describe_sale_status(self, platform_name: str, status: str) -> str:
        status_lower = (status or '').lower()
        platform_key = platform_name.lower()

        if platform_key == 'reverb':
            if status_lower == 'sold':
                return 'Sold on Reverb'
            if status_lower == 'ended':
                return 'Ended on Reverb'
        elif platform_key == 'ebay':
            if status_lower in {'endedwithsales', 'completed'}:
                return 'Sold on eBay'
            if status_lower == 'ended':
                return 'Ended on eBay'
        elif platform_key == 'shopify':
            if status_lower == 'archived':
                return 'Sold on Shopify (archived)'
        elif platform_key == 'vr':
            if status_lower == 'sold':
                return 'Sold on Vintage & Rare'
            if status_lower == 'ended':
                return 'Ended on Vintage & Rare'

        if status_lower:
            return f"{status_lower.capitalize()} on {platform_name.capitalize()}"
        return f"Status unknown on {platform_name.capitalize()}"

    async def _propagate_end_listing(
        self,
        product: Product,
        source_platforms: Union[str, Set[str]],
        dry_run: bool,
        platform_filter: Optional[Set[str]] = None,
    ) -> Tuple[List[str], List[str], int]:
        """
        Ends listings on other platforms.
        
        Args:
            product: The product to end listings for
            source_platforms: Either a single platform name (str) or set of platform names
            dry_run: Whether to simulate the action
            
        Returns:
            Tuple of (successful_platforms, action_log, failed_count)
        """
        # Convert single platform to set for consistent handling
        if isinstance(source_platforms, str):
            source_platforms = {source_platforms}
            
        action_log: List[str] = []
        successful_platforms = []
        failed_count = 0
        all_platform_links = (await self.db.execute(select(PlatformCommon).where(PlatformCommon.product_id == product.id))).scalars().all()

        tasks, task_map = [], {}
        for link in all_platform_links:
            if link.platform_name in source_platforms:
                continue

            if platform_filter is not None and link.platform_name not in platform_filter:
                continue

            if link.status != ListingStatus.ACTIVE.value:
                if dry_run:
                    action_desc = (
                        f"[DRY RUN][ACTION] Product #{product.id} (SKU: {product.sku}) already {link.status} on {link.platform_name.upper()}. "
                        "Would ensure specialist tables reflect the ended status."
                    )
                else:
                    action_desc = (
                        f"[INFO] Product #{product.id} (SKU: {product.sku}) already {link.status} on {link.platform_name.upper()}. "
                        "Syncing local specialist tables."
                    )
                action_log.append(action_desc)
                successful_platforms.append(link.platform_name)
                continue

            service = self.platform_services.get(link.platform_name)
            if service and hasattr(service, 'mark_item_as_sold'):
                if dry_run:
                    action_desc = f"[DRY RUN][ACTION] Product #{product.id} (SKU: {product.sku}) sold on {'/'.join(sorted(source_platforms)).upper()}. Would end listing on {link.platform_name.upper()} (ID: {link.external_id})."
                    action_log.append(action_desc)
                    logger.info(action_desc)
                    successful_platforms.append(link.platform_name)
                else:
                    logger.info(
                        "Queueing mark_item_as_sold for product %s on %s (external_id=%s)",
                        product.id,
                        link.platform_name,
                        link.external_id,
                    )
                    tasks.append(service.mark_item_as_sold(link.external_id))
                    task_map[len(tasks)-1] = (link.platform_name, link.external_id, product.sku)
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, res in enumerate(results):
                platform_name, external_id, sku = task_map.get(i, ("Unknown", "N/A", "N/A"))
                
                if isinstance(res, Exception) or res is False:
                    failed_count += 1
                    error_msg = (
                        f"[ERROR] Product #{product.id} (SKU: {sku}) on {platform_name.upper()} (ID: {external_id})"
                        f" -> FAILED to end. Reason: {res}"
                    )
                    action_log.append(error_msg)
                    logger.error(error_msg)
                else:
                    success_msg = f"[SUCCESS] Product #{product.id} (SKU: {sku}) on {platform_name.upper()} (ID: {external_id}) -> Listing ended successfully."
                    action_log.append(success_msg)
                    logger.info(success_msg)
                    successful_platforms.append(platform_name)
        
        return successful_platforms, action_log, failed_count

    async def _get_current_specialist_prices(self, product_id: int) -> Dict[str, Optional[float]]:
        """Fetches the current price for a product from each specialist table."""
        query = text("""
            SELECT
                pc.platform_name,
                COALESCE(
                    rl.list_price,
                    el.price,
                    sl.price,
                    vl.price_notax
                ) AS specialist_price
            FROM
                platform_common pc
            LEFT JOIN
                reverb_listings rl ON pc.platform_name = 'reverb' AND pc.id = rl.platform_id
            LEFT JOIN
                ebay_listings el ON pc.platform_name = 'ebay' AND pc.id = el.platform_id
            LEFT JOIN
                shopify_listings sl ON pc.platform_name = 'shopify' AND pc.id = sl.platform_id
            LEFT JOIN
                vr_listings vl ON pc.platform_name = 'vr' AND pc.id = vl.platform_id
            WHERE
                pc.product_id = :product_id
        """)
        result = await self.db.execute(query, {"product_id": product_id})
        return {row.platform_name: row.specialist_price for row in result.fetchall()}
    
    async def propagate_price_update_from_master(self, product: Product, new_price: float, platforms_to_update: List[str], dry_run: bool) -> Tuple[List[str], List[str], int]:
        """Pushes the master price to specified active platform listings, checking first if an update is needed."""
        action_log = []
        successful_platforms = []
        failed_count = 0
        
        # Get all current specialist prices from the DB
        current_prices = await self._get_current_specialist_prices(product.id)
        
        all_platform_links = (await self.db.execute(select(PlatformCommon).where(PlatformCommon.product_id == product.id))).scalars().all()

        for link in all_platform_links:
            # Skip if not in the requested list of platforms (unless 'all' is specified)
            if 'all' not in platforms_to_update and link.platform_name not in platforms_to_update:
                continue
                
            if link.status != ListingStatus.ACTIVE.value:
                action_log.append(f"[INFO] Skipped {link.platform_name.upper()} listing {link.external_id} (not active).")
                continue
            
            # --- THE NEW PRE-CHECK ---
            current_specialist_price = current_prices.get(link.platform_name)
            if current_specialist_price is not None and abs(float(current_specialist_price) - new_price) < 0.01:
                action_log.append(f"[INFO] Skipped {link.platform_name.upper()} listing {link.external_id} (price already matches master).")
                continue
            # --- END OF PRE-CHECK ---
            
            service = self.platform_services.get(link.platform_name)
            if service and hasattr(service, 'update_listing_price'):
                action_desc = f"[DRY RUN][ACTION] Would push master price £{new_price:.2f} to {link.platform_name.upper()} listing {link.external_id}."

                if not dry_run:
                    if link.platform_name == "vr":
                        snapshot = self._snapshot_product(product)
                        logger.info(
                            "Queueing VR background price update for %s",
                            link.external_id,
                        )
                        task = asyncio.create_task(
                            self._run_vr_update_background(
                                snapshot,
                                link.external_id,
                                {"base_price"},
                            )
                        )
                        self._track_background_task(task)
                        action_desc = (
                            f"[QUEUED] Scheduled VR price update to £{new_price:.2f}"
                            f" for listing {link.external_id}."
                        )
                        successful_platforms.append(link.platform_name)
                        action_log.append(action_desc)
                        continue
                    try:
                        success = await service.update_listing_price(link.external_id, new_price)
                        if success:
                            action_desc = f"[SUCCESS] Pushed master price £{new_price:.2f} to {link.platform_name.upper()} listing {link.external_id}."
                            successful_platforms.append(link.platform_name)
                        else:
                            failed_count += 1
                            action_desc = f"[ERROR] FAILED to push master price to {link.platform_name.upper()} listing {link.external_id}."
                    except Exception as e:
                        failed_count += 1
                        action_desc = f"[ERROR] EXCEPTION pushing master price to {link.platform_name.upper()} listing {link.external_id}: {e}"
                
                action_log.append(action_desc)
            else:
                action_log.append(f"[WARNING] No 'update_listing_price' method found for service: {link.platform_name}")
                
        return successful_platforms, action_log, failed_count
    
    def _is_sale_event(self, platform_name: str, change_data: dict) -> bool:
        """
        Determines if a status change constitutes a sale or an equivalent event
        that requires ending listings on other platforms.
        """
        raw_new_status = change_data.get('new') if change_data else None
        normalized_status = _normalize_platform_status(platform_name, raw_new_status)

        if not normalized_status:
            return False

        return normalized_status in {ListingStatus.SOLD.value, ListingStatus.ENDED.value}

    async def _handle_quantity_change(self, event: SyncEvent, summary: Dict, actions: List, dry_run: bool) -> bool:
        """Adjust local inventory when the platform reports a quantity change."""
        if not event.product_id:
            event.notes = "Event is missing product_id, cannot process quantity change."
            return False

        product = await self.db.get(Product, event.product_id)
        if not product:
            event.notes = f"Product with ID {event.product_id} not found."
            return False

        change_data = event.change_data or {}
        new_quantity = change_data.get('new_quantity')
        old_quantity = change_data.get('old_quantity')

        try:
            new_quantity_int = int(new_quantity)
        except (TypeError, ValueError):
            event.notes = f"Invalid new quantity value: {new_quantity}"
            return False

        try:
            old_quantity_int = int(old_quantity) if old_quantity is not None else None
        except (TypeError, ValueError):
            old_quantity_int = None

        summary['non_sale_changes'] += 1
        action_desc = (
            f"[{'DRY RUN' if dry_run else 'ACTION'}] eBay inventory change for Product #{product.id}: "
            f"{old_quantity_int} -> {new_quantity_int}"
        )

        if dry_run:
            actions.append(action_desc)
            summary['actions_taken'] += 1
            event.notes = "Dry run - quantity change acknowledged."
            return True

        product_was_stocked = bool(product.is_stocked_item)

        if product_was_stocked:
            product.quantity = new_quantity_int
            if new_quantity_int > 0 and product.status == ProductStatus.SOLD:
                product.status = ProductStatus.ACTIVE
            if new_quantity_int == 0:
                product.status = ProductStatus.SOLD
        else:
            # Non-stocked items should only ever show 0 or 1
            if new_quantity_int == 0:
                product.status = ProductStatus.SOLD
        self.db.add(product)

        # Update listing quantities if we have a link
        platform_link = None
        if event.platform_common_id:
            platform_stmt = select(PlatformCommon).where(PlatformCommon.id == event.platform_common_id)
            platform_link = (await self.db.execute(platform_stmt)).scalar_one_or_none()
            if platform_link:
                platform_link.status = ListingStatus.ACTIVE.value if new_quantity_int > 0 else ListingStatus.ENDED.value
                platform_link.sync_status = SyncStatus.SYNCED.value
                self.db.add(platform_link)

            listing_stmt = select(EbayListing).where(EbayListing.platform_id == event.platform_common_id)
            listing = (await self.db.execute(listing_stmt)).scalar_one_or_none()
            if listing:
                listing.quantity_available = new_quantity_int
                total_quantity = change_data.get('total_quantity')
                if total_quantity is not None:
                    try:
                        listing.quantity = int(total_quantity)
                    except (TypeError, ValueError):
                        pass
                self.db.add(listing)

        actions.append(action_desc)
        summary['actions_taken'] += 1
        event.notes = f"Quantity updated to {new_quantity_int}."
        return True

    async def _handle_order_sale(self, event: SyncEvent, summary: Dict, actions: List, dry_run: bool) -> bool:
        """
        Handle an order_sale event for stocked (inventoried) items.

        This decrements quantity on RIFF and propagates to other platforms:
        - eBay: Update quantity
        - Shopify: Update inventory
        - VR: No action if qty > 0 (VR doesn't support multi-qty)
        - If qty reaches 0: End listings on all platforms
        """
        if not event.product_id:
            event.notes = "Event is missing product_id, cannot process order sale."
            return False

        product = await self.db.get(Product, event.product_id)
        if not product:
            event.notes = f"Product {event.product_id} not found."
            return False

        change_data = event.change_data or {}
        quantity_sold = change_data.get('quantity_sold', 1)
        order_number = change_data.get('order_number', 'unknown')
        current_qty = product.quantity or 0

        try:
            quantity_sold = int(quantity_sold)
        except (TypeError, ValueError):
            quantity_sold = 1

        new_quantity = max(0, current_qty - quantity_sold)

        action_desc = (
            f"[{'DRY RUN' if dry_run else 'ACTION'}] Order sale for Product #{product.id} "
            f"(order {order_number}): qty {current_qty} -> {new_quantity}"
        )

        if dry_run:
            actions.append(action_desc)
            summary['actions_taken'] += 1
            event.notes = f"Dry run - would decrement quantity to {new_quantity}."
            return True

        # 1. Update RIFF product quantity
        product.quantity = new_quantity
        if new_quantity == 0:
            product.status = ProductStatus.SOLD
            summary['sales'] += 1
            logger.info(f"Product #{product.id} quantity reached 0. Marking as SOLD.")
        self.db.add(product)

        # 2. Update reverb_listings.inventory_quantity
        reverb_listing_stmt = (
            select(ReverbListing)
            .join(PlatformCommon, ReverbListing.platform_id == PlatformCommon.id)
            .where(PlatformCommon.product_id == product.id)
        )
        reverb_listing_result = await self.db.execute(reverb_listing_stmt)
        reverb_listing = reverb_listing_result.scalar_one_or_none()
        if reverb_listing:
            reverb_listing.inventory_quantity = new_quantity
            self.db.add(reverb_listing)
            logger.info(f"Updated reverb_listings.inventory_quantity to {new_quantity} for product #{product.id}")

        # 3. Mark the order as processed
        order_uuid = change_data.get('order_uuid')
        if order_uuid:
            from app.models.reverb_order import ReverbOrder
            order_stmt = select(ReverbOrder).where(ReverbOrder.order_uuid == order_uuid)
            order_result = await self.db.execute(order_stmt)
            order = order_result.scalar_one_or_none()
            if order:
                order.sale_processed = True
                order.sale_processed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                self.db.add(order)
                logger.info(f"Marked order {order_number} as sale_processed")

        # 4. Propagate to other platforms
        propagation_results = []

        # eBay: Update quantity
        ebay_link_stmt = select(PlatformCommon).where(
            PlatformCommon.product_id == product.id,
            PlatformCommon.platform_name == "ebay",
            PlatformCommon.status == ListingStatus.ACTIVE.value,
        )
        ebay_link_result = await self.db.execute(ebay_link_stmt)
        ebay_link = ebay_link_result.scalar_one_or_none()

        if ebay_link and ebay_link.external_id:
            try:
                ebay_service = self.platform_services.get("ebay")
                if ebay_service and hasattr(ebay_service, 'update_quantity'):
                    await ebay_service.update_quantity(ebay_link.external_id, new_quantity)
                    propagation_results.append(f"eBay: qty updated to {new_quantity}")
                    logger.info(f"Updated eBay quantity to {new_quantity} for item {ebay_link.external_id}")

                    # Update local ebay_listings
                    from app.models.ebay import EbayListing
                    ebay_listing_stmt = select(EbayListing).where(EbayListing.platform_id == ebay_link.id)
                    ebay_listing = (await self.db.execute(ebay_listing_stmt)).scalar_one_or_none()
                    if ebay_listing:
                        ebay_listing.quantity_available = new_quantity
                        self.db.add(ebay_listing)

                    if new_quantity == 0:
                        ebay_link.status = ListingStatus.ENDED.value
                        self.db.add(ebay_link)
                else:
                    propagation_results.append("eBay: service not available for qty update")
            except Exception as e:
                propagation_results.append(f"eBay: failed - {str(e)}")
                logger.warning(f"Failed to update eBay quantity: {e}")

        # Shopify: Update inventory
        shopify_link_stmt = select(PlatformCommon).where(
            PlatformCommon.product_id == product.id,
            PlatformCommon.platform_name == "shopify",
            PlatformCommon.status == ListingStatus.ACTIVE.value,
        )
        shopify_link_result = await self.db.execute(shopify_link_stmt)
        shopify_link = shopify_link_result.scalar_one_or_none()

        if shopify_link and shopify_link.external_id:
            try:
                shopify_service = self.platform_services.get("shopify")
                if shopify_service and hasattr(shopify_service, 'update_inventory'):
                    await shopify_service.update_inventory(shopify_link.external_id, new_quantity)
                    propagation_results.append(f"Shopify: inventory updated to {new_quantity}")
                    logger.info(f"Updated Shopify inventory to {new_quantity} for product {shopify_link.external_id}")

                    if new_quantity == 0:
                        shopify_link.status = ListingStatus.ENDED.value
                        self.db.add(shopify_link)
                else:
                    propagation_results.append("Shopify: service not available for inventory update")
            except Exception as e:
                propagation_results.append(f"Shopify: failed - {str(e)}")
                logger.warning(f"Failed to update Shopify inventory: {e}")

        # VR: Only take action if qty reaches 0 (end listing)
        # VR doesn't support multi-qty, so no action needed when qty > 0
        if new_quantity == 0:
            vr_link_stmt = select(PlatformCommon).where(
                PlatformCommon.product_id == product.id,
                PlatformCommon.platform_name == "vr",
                PlatformCommon.status == ListingStatus.ACTIVE.value,
            )
            vr_link_result = await self.db.execute(vr_link_stmt)
            vr_link = vr_link_result.scalar_one_or_none()

            if vr_link and vr_link.external_id:
                try:
                    vr_service = self.platform_services.get("vr")
                    if vr_service and hasattr(vr_service, 'end_listing'):
                        await vr_service.end_listing(vr_link.external_id)
                        propagation_results.append("VR: listing ended (qty=0)")
                        vr_link.status = ListingStatus.ENDED.value
                        self.db.add(vr_link)
                        logger.info(f"Ended VR listing for product #{product.id}")
                    else:
                        propagation_results.append("VR: service not available to end listing")
                except Exception as e:
                    propagation_results.append(f"VR: failed to end - {str(e)}")
                    logger.warning(f"Failed to end VR listing: {e}")
        else:
            propagation_results.append(f"VR: no action (qty={new_quantity} > 0)")

        actions.append(action_desc)
        if propagation_results:
            actions.extend([f"  - {r}" for r in propagation_results])

        summary['actions_taken'] += 1
        summary['non_sale_changes'] += 1

        # Send sale alert email (same as non-inventoried items)
        sale_amount = change_data.get('sale_amount')
        listing_url = change_data.get('listing_url')
        try:
            propagated_platforms_list = [p.split(':')[0] for p in propagation_results if 'updated' in p.lower() or 'ended' in p.lower()]
            await self._send_sale_alert(
                product=product,
                platform="reverb",
                sale_price=float(sale_amount) if sale_amount else None,
                external_reference=order_number,
                sale_status=f"Order Sale (qty: {quantity_sold})",
                listing_url=listing_url,
                detected_at=datetime.now(timezone.utc).isoformat(),
                propagated_platforms=propagated_platforms_list if propagated_platforms_list else None,
            )
            logger.info(f"Sale alert email queued for order {order_number}")
        except Exception as e:
            logger.warning(f"Failed to send sale alert email for order {order_number}: {e}")

        event.notes = f"Order sale processed. Qty {current_qty} -> {new_quantity}. " + "; ".join(propagation_results)
        return True

    async def sync_product_to_platforms(
        self, 
        product_id: int, 
        platforms: List[str],
        db: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """
        Synchronize a product to specified platforms.
        
        Args:
            product_id: ID of the product to sync
            platforms: List of platform names to sync to (e.g., ["ebay", "reverb", "vr"])
            db: Optional database session override
            
        Returns:
            Dict with sync results per platform
        """
        if db is None:
            db = self.db
            
        # Find the product
        query = select(Product).where(Product.id == product_id)
        result = await db.execute(query)
        product = result.scalar_one_or_none()
        
        if not product:
            return {"status": "error", "message": "Product not found"}
            
        results = {}
        
        # Process each requested platform
        for platform in platforms:
            try:
                if platform == "ebay":
                    # Handle eBay synchronization
                    from app.services.ebay_service import EbayService
                    ebay_service = EbayService(db)
                    ebay_result = await ebay_service.sync_product(product)
                    results["ebay"] = ebay_result
                    
                elif platform == "reverb":
                    # Handle Reverb synchronization  
                    from app.services.reverb_service import ReverbService
                    reverb_service = ReverbService(db)
                    reverb_result = await reverb_service.sync_product(product)
                    results["reverb"] = reverb_result
                    
                elif platform == "vr":
                    # Handle VintageAndRare synchronization
                    from app.services.vintageandrare.client import VintageAndRareClient
                    vr_client = VintageAndRareClient()
                    
                    # Convert product to the format expected by VR client
                    product_data = {
                        "id": product.id,
                        "brand": product.brand,
                        "model": product.model,
                        "description": product.description,
                        "category": product.category,
                        "price": product.base_price,
                        "condition": product.condition.value,
                        "year": product.year,
                        "finish": product.finish,
                        "primary_image": product.primary_image,
                        "additional_images": product.additional_images
                    }
                    
                    # Create listing in VintageAndRare
                    vr_result = await vr_client.create_listing(product_data, test_mode=False)
                    results["vr"] = {
                        "status": "success" if vr_result.get("external_id") else "error",
                        "id": vr_result.get("external_id"),
                        "message": vr_result.get("message", "")
                    }
                    
                    # Update platform_common record
                    if vr_result.get("external_id"):
                        await self._update_platform_common(
                            db, product.id, "vr", vr_result["external_id"], 
                            ListingStatus.ACTIVE, SyncStatus.SYNCED
                        )
                        
                else:
                    results[platform] = {
                        "status": "error", 
                        "message": f"Unknown platform: {platform}"
                    }
                    
            except Exception as e:
                logger.exception(f"Error syncing to {platform}: {str(e)}")
                results[platform] = {
                    "status": "error",
                    "message": str(e)
                }
                
                # Update platform_common with error status
                await self._update_platform_common(
                    db, product.id, platform, None,
                    ListingStatus.DRAFT, SyncStatus.ERROR
                )
                
        return results
    
    async def propagate_stock_update(
        self, 
        product_id: int, 
        new_quantity: int,
        source_platform: str = "local"
    ) -> bool:
        """
        Propagate a stock update to all platforms through StockManager.
        
        Args:
            product_id: ID of the product with changed stock
            new_quantity: New stock quantity
            source_platform: Platform that originated the update
            
        Returns:
            True if queued successfully, False otherwise
        """
        if self.stock_manager is None:
            logger.error("Stock manager not available")
            return False
            
        try:
            # Create stock update event
            event = StockUpdateEvent(
                product_id=product_id,
                platform=source_platform,
                new_quantity=new_quantity,
                timestamp=datetime.now(timezone.utc)
            )
            
            # Process the update directly - useful for API calls
            await self.stock_manager.process_stock_update(event)
            return True
            
        except Exception as e:
            logger.exception(f"Error propagating stock update: {str(e)}")
            return False

    async def propagate_product_edit(
        self,
        product_id: int,
        original_values: Dict[str, Any],
        changed_fields: Set[str],
        *,
        platform_price_overrides: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        product = await self.db.get(Product, product_id)
        if not product:
            return {"status": "error", "message": "product_not_found"}

        platform_links = (
            await self.db.execute(
                select(PlatformCommon).where(PlatformCommon.product_id == product_id)
            )
        ).scalars().all()

        results: Dict[str, Any] = {}

        overrides = {
            (key or "").lower(): value
            for key, value in (platform_price_overrides or {}).items()
            if value is not None
        }

        non_vr_links = [link for link in platform_links if link.platform_name != "vr"]
        vr_links = [link for link in platform_links if link.platform_name == "vr"]

        tasks = []
        task_platforms: List[str] = []

        for link in non_vr_links:
            service = self.platform_services.get(link.platform_name)
            if not service or not hasattr(service, "apply_product_update"):
                continue
            task_platforms.append(link.platform_name)
            tasks.append(service.apply_product_update(product, link, changed_fields))

        if tasks:
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            for platform_name, response in zip(task_platforms, responses):
                if isinstance(response, Exception):
                    logger.error(
                        "Error applying update for %s: %s",
                        platform_name,
                        response,
                        exc_info=True,
                    )
                    results[f"{platform_name}_error"] = str(response)
                else:
                    results[platform_name] = response

        if "base_price" in changed_fields or overrides:
            default_price = float(product.base_price or 0)
            for link in non_vr_links:
                if not link.external_id:
                    continue
                service = self.platform_services.get(link.platform_name)
                if not service or not hasattr(service, "update_listing_price"):
                    continue
                try:
                    platform_key = (link.platform_name or "").lower()
                    desired_price = overrides.get(platform_key, default_price)
                    success = await service.update_listing_price(link.external_id, desired_price)
                except Exception as exc:
                    logger.error(
                        "Error updating price for %s listing %s: %s",
                        link.platform_name,
                        link.external_id,
                        exc,
                        exc_info=True,
                    )
                    results[f"{link.platform_name}_price_error"] = str(exc)
                    continue

                status_key = f"{link.platform_name}_price"
                if success:
                    results[status_key] = "updated"
                    timestamp = datetime.utcnow()

                    if link.platform_name == "shopify":
                        listing_stmt = select(ShopifyListing).where(ShopifyListing.platform_id == link.id)
                        listing_result = await self.db.execute(listing_stmt)
                        listing = listing_result.scalar_one_or_none()
                        if listing:
                            listing.price = desired_price
                            listing.updated_at = timestamp
                            listing.last_synced_at = timestamp
                            self.db.add(listing)
                    elif link.platform_name == "ebay":
                        listing_stmt = select(EbayListing).where(EbayListing.platform_id == link.id)
                        listing_result = await self.db.execute(listing_stmt)
                        listing = listing_result.scalar_one_or_none()
                        if listing:
                            listing.price = desired_price
                            listing.updated_at = timestamp
                            listing.last_synced_at = timestamp
                            self.db.add(listing)
                    elif link.platform_name == "reverb":
                        listing_stmt = select(ReverbListing).where(ReverbListing.platform_id == link.id)
                        listing_result = await self.db.execute(listing_stmt)
                        listing = listing_result.scalar_one_or_none()
                        if listing:
                            listing.list_price = desired_price
                            listing.updated_at = timestamp
                            listing.last_synced_at = timestamp
                            self.db.add(listing)

                    platform_data = dict(link.platform_specific_data or {})
                    platform_data["price"] = desired_price
                    link.platform_specific_data = platform_data
                    link.last_sync = timestamp
                    link.sync_status = SyncStatus.SYNCED.value
                    self.db.add(link)
                else:
                    results[status_key] = "failed"

        if vr_links and ("base_price" in changed_fields or "vr" in overrides):
            desired_price = overrides.get("vr", float(product.base_price or 0))
            service = self.platform_services.get("vr")
            if service and hasattr(service, "update_listing_price"):
                async def _run_vr_price_update(external_id: str, target_price: float) -> None:
                    try:
                        success = await service.update_listing_price(external_id, target_price)
                        if not success:
                            logger.warning(
                                "VR price update for listing %s reported failure",
                                external_id,
                            )
                    except Exception as exc:
                        logger.error(
                            "Error updating VR price for listing %s: %s",
                            external_id,
                            exc,
                            exc_info=True,
                        )

                timestamp = datetime.utcnow()
                for link in vr_links:
                    if not link.external_id:
                        continue

                    listing_stmt = select(VRListing).where(VRListing.platform_id == link.id)
                    listing_result = await self.db.execute(listing_stmt)
                    listing = listing_result.scalar_one_or_none()
                    if listing:
                        listing.price_notax = desired_price
                        listing.last_synced_at = timestamp
                        self.db.add(listing)

                    platform_data = dict(link.platform_specific_data or {})
                    platform_data["price"] = desired_price
                    link.platform_specific_data = platform_data
                    link.last_sync = timestamp
                    link.sync_status = SyncStatus.SYNCED.value
                    self.db.add(link)

                    task = asyncio.create_task(_run_vr_price_update(link.external_id, desired_price))
                    self._track_background_task(task)

                results["vr_price"] = "queued"

        # Handle VR quantity going to zero (end listing)
        for link in vr_links:
            service = self.platform_services.get("vr")
            if "quantity" in changed_fields and link.external_id:
                old_qty = int(original_values.get("quantity") or 0)
                new_qty = int(product.quantity or 0)
                if old_qty > 0 and new_qty == 0 and service and hasattr(service, "mark_item_as_sold"):
                    try:
                        await service.mark_item_as_sold(link.external_id)
                        link.status = ListingStatus.ENDED.value
                        self.db.add(link)
                        results["vr"] = "ended"
                    except Exception as exc:
                        logger.error("Failed to mark VR listing %s as sold: %s", link.external_id, exc)
                        results["vr_error"] = str(exc)

        # Schedule VR detail updates in the background
        vr_fields = {"title", "model", "description", "brand", "base_price"}
        if vr_links and (changed_fields & vr_fields):
            snapshot = self._snapshot_product(product)
            for link in vr_links:
                if not link.external_id:
                    continue
                logger.info(
                    "Queueing VR background update for %s (fields: %s)",
                    link.external_id,
                    ",".join(sorted(changed_fields & vr_fields)),
                )
                task = asyncio.create_task(
                    self._run_vr_update_background(snapshot, link.external_id, changed_fields)
                )
                self._track_background_task(task)
            results["vr_detail_update"] = "queued"

        await self.db.commit()
        return results

    def _snapshot_product(self, product: Product) -> Dict[str, Any]:
        return {
            "sku": product.sku,
            "brand": product.brand,
            "model": product.model,
            "title": product.title,
            "description": product.description,
            "base_price": float(product.base_price or 0),
            "year": product.year,
            "finish": product.finish,
            "category": product.category,
            "primary_image": product.primary_image,
            "additional_images": product.additional_images,
            "video_url": product.video_url,
        }

    def _track_background_task(self, task: asyncio.Task) -> None:
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _run_vr_update_background(
        self,
        product_snapshot: Dict[str, Any],
        external_id: str,
        changed_fields: Set[str],
    ) -> None:
        logger.info(
            "Starting VR background update for %s (fields: %s)",
            external_id,
            ",".join(sorted(changed_fields)),
        )
        semaphore = self._vr_semaphore
        async with semaphore:
            service = self.platform_services.get("vr")
            if not service or not hasattr(service, "apply_product_update_from_snapshot"):
                logger.info("VR service does not support detail updates; skipping")
                return

            try:
                loop = asyncio.get_running_loop()
                if self.vr_executor:
                    result = await loop.run_in_executor(
                        self.vr_executor,
                        lambda: service.apply_product_update_from_snapshot(
                            product_snapshot,
                            external_id,
                            changed_fields,
                        ),
                    )
                else:
                    result = await loop.run_in_executor(
                        None,
                        lambda: service.apply_product_update_from_snapshot(
                            product_snapshot,
                            external_id,
                            changed_fields,
                        ),
                    )
                logger.info("VR background update for %s completed: %s", external_id, result)

                if isinstance(result, dict):
                    status = result.get("status")
                    if status == "success":
                        applied_fields = result.get("applied_fields")
                        await service.update_local_listing_metadata(
                            external_id,
                            product_snapshot,
                            changed_fields,
                            applied_fields=applied_fields,
                        )
                    else:
                        logger.warning(
                            "VR edit for %s completed with status %s: %s",
                            external_id,
                            status,
                            result,
                        )
                else:
                    logger.warning(
                        "VR edit for %s returned unexpected response type: %s",
                        external_id,
                        type(result),
                    )
            except Exception as exc:
                logger.error(
                    "Error running VR background update for %s: %s",
                    external_id,
                    exc,
                    exc_info=True,
                )
        logger.info("Finished VR background update for %s", external_id)
    
    async def _update_platform_common(
        self, 
        db: AsyncSession,
        product_id: int,
        platform_name: str,
        external_id: Optional[str],
        status: ListingStatus,
        sync_status: SyncStatus
    ) -> Optional[PlatformCommon]:
        """
        Update or create platform_common record for a product/platform.
        
        Args:
            db: Database session
            product_id: Product ID
            platform_name: Platform name (e.g., "ebay")
            external_id: External platform ID (or None)
            status: Listing status enum value
            sync_status: Sync status enum value
            
        Returns:
            Updated or created PlatformCommon record (or None on error)
        """
        try:
            # Find existing record
            query = select(PlatformCommon).where(
                (PlatformCommon.product_id == product_id) & 
                (PlatformCommon.platform_name == platform_name)
            )
            result = await db.execute(query)
            platform_common = result.scalar_one_or_none()
            
            now = datetime.now(timezone.utc)
            
            if platform_common:
                # Update existing record
                platform_common.external_id = external_id or platform_common.external_id
                platform_common.status = status.value
                platform_common.sync_status = sync_status.value
                platform_common.last_sync = now
                platform_common.updated_at = now
            else:
                # Create new record
                platform_common = PlatformCommon(
                    product_id=product_id,
                    platform_name=platform_name,
                    external_id=external_id,
                    status=status.value,
                    sync_status=sync_status.value,
                    last_sync=now,
                    created_at=now,
                    updated_at=now
                )
                db.add(platform_common)
                
            await db.commit()
            return platform_common
            
        except Exception as e:
            await db.rollback()
            logger.exception(f"Error updating platform_common: {str(e)}")
            return None

    async def _update_local_platform_status(self, product_id: int, platform_name: str, new_status: str):
        """
        Performs a two-stage update of a listing's status on both the manager (platform_common)
        and specialist tables.
        """
        logger.info(f"Updating local status for Product #{product_id} on {platform_name} to '{new_status}'.")
        canonical_status = _normalize_platform_status(platform_name, new_status) or new_status

        # Stage 1: Update the Manager (platform_common)
        pc_stmt = (
            update(PlatformCommon)
            .where(PlatformCommon.product_id == product_id)
            .where(PlatformCommon.platform_name == platform_name)
            .values(status=canonical_status, sync_status=SyncStatus.SYNCED.value)
        )
        await self.db.execute(pc_stmt)

        # Stage 2: Update the Specialist table
        # We need to import the specialist models at the top of the file for this to work
        from app.models.reverb import ReverbListing
        from app.models.ebay import EbayListing
        from app.models.shopify import ShopifyListing
        from app.models.vr import VRListing
        
        specialist_tables = {
            "reverb": {"table": ReverbListing, "status_col": "reverb_state"},
            "ebay": {"table": EbayListing, "status_col": "listing_status"},
            "shopify": {"table": ShopifyListing, "status_col": "status"},
            "vr": {"table": VRListing, "status_col": "vr_state"},
        }

        if platform_name in specialist_tables:
            config = specialist_tables[platform_name]
            pc_id_stmt = select(PlatformCommon.id).where(
                PlatformCommon.product_id == product_id,
                PlatformCommon.platform_name == platform_name
            )
            platform_common_id = (await self.db.execute(pc_id_stmt)).scalar_one_or_none()

            if platform_common_id:
                # Use a dictionary for the values to set the column name dynamically
                values_to_update = {config["status_col"]: canonical_status}
                specialist_stmt = (
                    update(config["table"])
                    .where(getattr(config["table"], 'platform_id') == platform_common_id)
                    .values(**values_to_update)
                )
                await self.db.execute(specialist_stmt)
            else:
                logger.warning(f"Could not find platform_common_id for Product #{product_id} on {platform_name} to update specialist table.")



class ChangeDetector:
    """Compares platform data vs PlatformCommon table to detect changes"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        
    async def detect_platform_changes(
        self, 
        platform: str, 
        platform_data: List[Dict[str, Any]]
    ) -> SyncReport:
        """
        Main entry point - detect all changes for a platform
        
        Args:
            platform: Platform name (ebay, reverb, shopify, vr)
            platform_data: List of items from platform API
            
        Returns:
            SyncReport with detected changes
        """
        start_time = datetime.now()
        changes = []
        errors = []
        
        try:
            # Get local data for this platform
            local_data = await self._get_local_platform_data(platform)
            
            # Convert to lookup dictionaries for efficient comparison
            platform_lookup = {item.get('external_id') or item.get('id'): item for item in platform_data}
            local_lookup = {item['external_id']: item for item in local_data if item['external_id']}
            
            # Detect changes
            changes.extend(await self._detect_status_changes(platform, platform_lookup, local_lookup))
            changes.extend(await self._detect_price_changes(platform, platform_lookup, local_lookup))
            changes.extend(await self._detect_content_changes(platform, platform_lookup, local_lookup))
            changes.extend(await self._detect_new_listings(platform, platform_lookup, local_lookup))
            changes.extend(await self._detect_removed_listings(platform, platform_lookup, local_lookup))
            
        except Exception as e:
            logger.exception(f"Error during change detection for {platform}")
            errors.append(f"Change detection error: {str(e)}")
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        return SyncReport(
            platform=platform,
            timestamp=start_time,
            total_platform_items=len(platform_data),
            total_local_items=len(local_data) if 'local_data' in locals() else 0,
            changes_detected=changes,
            errors=errors,
            processing_time_seconds=processing_time
        )
    
    async def _get_local_platform_data(self, platform: str) -> List[Dict[str, Any]]:
        """Get current local data for platform from PlatformCommon + related tables"""
        try:
            if platform == "ebay":
                query = text("""
                    SELECT pc.external_id, pc.product_id, pc.status, pc.last_sync,
                           p.sku, p.brand, p.model, p.title, p.base_price,
                           el.price AS price, el.listing_status
                    FROM platform_common pc
                    JOIN products p ON pc.product_id = p.id
                    LEFT JOIN ebay_listings el ON pc.external_id = el.ebay_item_id
                    WHERE pc.platform_name = 'ebay'
                """)
            elif platform == "reverb":
                query = text("""
                    SELECT pc.external_id, pc.product_id, pc.status, pc.last_sync,
                           p.sku, p.brand, p.model, p.title, p.base_price,
                           rl.list_price, rl.reverb_state
                    FROM platform_common pc
                    JOIN products p ON pc.product_id = p.id
                    LEFT JOIN reverb_listings rl ON CONCAT('REV-', pc.external_id) = rl.reverb_listing_id
                    WHERE pc.platform_name = 'reverb'
                """)
            elif platform == "shopify":
                query = text("""
                    SELECT pc.external_id, pc.product_id, pc.status, pc.last_sync,
                           p.sku, p.brand, p.model, p.title, p.base_price,
                           sl.price, sl.status
                    FROM platform_common pc
                    JOIN products p ON pc.product_id = p.id
                    LEFT JOIN shopify_listings sl ON pc.id = sl.platform_id
                    WHERE pc.platform_name = 'shopify'
                """)
            elif platform == "vr":
                query = text("""
                    SELECT pc.external_id, pc.product_id, pc.status, pc.last_sync,
                           p.sku, p.brand, p.model, p.title, p.base_price,
                           vl.price_notax, vl.vr_state
                    FROM platform_common pc
                    JOIN products p ON pc.product_id = p.id
                    LEFT JOIN vr_listings vl ON pc.external_id = vl.vr_listing_id
                    WHERE pc.platform_name = 'vr'
                """)
            
            result = await self.db.execute(query)
            return [dict(row._mapping) for row in result.fetchall()]
            
        except Exception as e:
            logger.exception(f"Error fetching local data for {platform}")
            return []
    
    async def _detect_status_changes(
        self, 
        platform: str, 
        platform_lookup: Dict, 
        local_lookup: Dict
    ) -> List[DetectedChange]:
        """Detect status changes (active->sold, active->ended, etc.)"""
        changes = []
        
        for external_id, platform_item in platform_lookup.items():
            if external_id not in local_lookup:
                continue
                
            local_item = local_lookup[external_id]
            
            # Get status from platform data (normalize field names)
            if platform == "ebay":
                platform_status = platform_item.get('listing_status') or platform_item.get('sellingStatus', {}).get('listingStatus')
            elif platform == "reverb":
                platform_status = platform_item.get('state') or platform_item.get('reverb_state')
            elif platform == "shopify":
                platform_status = platform_item.get('status')
            elif platform == "vr":
                platform_status = platform_item.get('state') or platform_item.get('vr_state')
            else:
                continue
            
            # Get local status
            local_status = local_item.get('status')
            
            # Compare statuses
            normalized_platform_status = _normalize_platform_status(platform, platform_status)
            normalized_local_status = _normalize_platform_status(platform, local_status)

            if (
                normalized_platform_status is not None
                and normalized_local_status is not None
                and normalized_platform_status != normalized_local_status
            ):
                changes.append(DetectedChange(
                    platform=platform,
                    external_id=external_id,
                    product_id=local_item.get('product_id'),
                    sku=local_item.get('sku', 'unknown'),
                    change_type="status_change",
                    field="status",
                    old_value=local_status,
                    new_value=platform_status,
                    requires_propagation=self._should_propagate_status_change(
                        normalized_platform_status,
                        normalized_local_status,
                    )
                ))

        return changes
    
    async def _detect_price_changes(
        self, 
        platform: str, 
        platform_lookup: Dict, 
        local_lookup: Dict
    ) -> List[DetectedChange]:
        """Detect price changes"""
        changes = []
        
        for external_id, platform_item in platform_lookup.items():
            if external_id not in local_lookup:
                continue
                
            local_item = local_lookup[external_id]

            if platform == "vr":
                # VR listings intentionally carry platform-specific markups; API feed also
                # returns inconsistent values. Skip automated price-drift detection.
                continue

            # Get price from platform data
            if platform == "ebay":
                platform_price = platform_item.get('current_price') or platform_item.get('buyItNowPrice', {}).get('value')
            elif platform == "reverb":
                platform_price = platform_item.get('price', {}).get('amount') if isinstance(platform_item.get('price'), dict) else platform_item.get('price')
            elif platform == "shopify":
                platform_price = platform_item.get('price')
            elif platform == "vr":
                platform_price = platform_item.get('price_notax')
            else:
                continue

            # Get local price (prefer platform-specific field, fall back to master price)
            if platform == "ebay":
                local_price = local_item.get('price')
            elif platform == "reverb":
                local_price = local_item.get('list_price')
            elif platform == "shopify":
                local_price = local_item.get('price')
            else:
                local_price = None

            if local_price is None:
                local_price = local_item.get('base_price')

            # Compare prices (with tolerance for floating point)
            if platform_price is not None and local_price is not None:
                try:
                    platform_price_float = float(platform_price)
                    local_price_float = float(local_price)

                    # Consider significant if difference > 1% or > £1
                    price_diff = abs(platform_price_float - local_price_float)
                    if price_diff > max(1.0, local_price_float * 0.01):
                        changes.append(DetectedChange(
                            platform=platform,
                            external_id=external_id,
                            product_id=local_item.get('product_id'),
                            sku=local_item.get('sku', 'unknown'),
                            change_type="price_change",
                            field="price",
                            old_value=local_price_float,
                            new_value=platform_price_float,
                            requires_propagation=True
                        ))
                except (ValueError, TypeError):
                    # Price comparison failed - log but continue
                    pass
        
        return changes
    
    async def _detect_content_changes(
        self, 
        platform: str, 
        platform_lookup: Dict, 
        local_lookup: Dict
    ) -> List[DetectedChange]:
        """Detect title/description changes"""
        changes = []
        
        for external_id, platform_item in platform_lookup.items():
            if external_id not in local_lookup:
                continue
                
            local_item = local_lookup[external_id]
            
            # Compare titles
            platform_title = platform_item.get('title')
            local_title = local_item.get('title')
            
            if platform_title and local_title and platform_title.strip() != local_title.strip():
                changes.append(DetectedChange(
                    platform=platform,
                    external_id=external_id,
                    product_id=local_item.get('product_id'),
                    sku=local_item.get('sku', 'unknown'),
                    change_type="title_change",
                    field="title",
                    old_value=local_title,
                    new_value=platform_title,
                    requires_propagation=False  # Usually don't propagate title changes
                ))
        
        return changes
    
    async def _detect_new_listings(
        self, 
        platform: str, 
        platform_lookup: Dict, 
        local_lookup: Dict
    ) -> List[DetectedChange]:
        """Detect new listings that appeared on platform"""
        changes = []
        
        for external_id, platform_item in platform_lookup.items():
            if external_id in local_lookup:
                continue

            # Attempt to suggest a match for specific platforms
            if platform == "vr":
                match_candidate = await self._suggest_vr_match(platform_item)
                if match_candidate:
                    changes.append(DetectedChange(
                        platform=platform,
                        external_id=external_id,
                        product_id=match_candidate["product"].id,
                        sku=match_candidate["product"].sku,
                        change_type="match_candidate",
                        field="listing",
                        old_value=match_candidate["platform_common"].external_id if match_candidate["platform_common"] else None,
                        new_value=external_id,
                        confidence=match_candidate["score"],
                        requires_propagation=False,
                        metadata={
                            "matched_by": "heuristic",
                            "score": match_candidate["score"],
                            "reason": match_candidate["reason"],
                            "candidate_product_id": match_candidate["product"].id,
                            "candidate_product_title": match_candidate["product"].title,
                        }
                    ))
                    continue

            # Default: treat as unknown new listing
            changes.append(DetectedChange(
                platform=platform,
                external_id=external_id,
                product_id=None,
                sku=platform_item.get('sku', 'unknown'),
                change_type="new_listing",
                field="listing",
                old_value=None,
                new_value=platform_item.get('title', 'New listing'),
                requires_propagation=False
            ))

        return changes

    async def _suggest_vr_match(self, platform_item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Attempt to match a V&R listing without a local record to an existing product."""

        sku = str(platform_item.get('sku') or platform_item.get('product_sku') or '').strip()
        brand_value = str(platform_item.get('brand_name') or platform_item.get('brand name') or '').lower().strip()
        model_value = str(platform_item.get('product_model_name') or platform_item.get('product model name') or '').lower().strip()
        finish_value = str(platform_item.get('product_finish') or platform_item.get('product finish') or '').lower().strip()
        year_value = str(platform_item.get('product_year') or platform_item.get('product year') or '').strip()
        description_value = str(platform_item.get('product_description') or platform_item.get('product description') or '').lower()

        try:
            price_value = float(platform_item.get('product_price') or platform_item.get('product price') or 0)
        except (TypeError, ValueError):
            price_value = 0.0

        candidates: List[Tuple[Product, Optional[PlatformCommon]]] = []
        seen_product_ids: Set[int] = set()

        # Direct SKU lookup
        if sku:
            product_stmt = select(Product).where(Product.sku == sku)
            product = await self.db.scalar(product_stmt)
            if product:
                pc_stmt = select(PlatformCommon).where(
                    PlatformCommon.product_id == product.id,
                    PlatformCommon.platform_name == 'vr'
                )
                platform_common = await self.db.scalar(pc_stmt)
                candidates.append((product, platform_common))
                seen_product_ids.add(product.id)

        if not brand_value:
            return None

        # Pending VR platform entries with matching brand
        pending_stmt = (
            select(Product, PlatformCommon)
            .outerjoin(
                PlatformCommon,
                (PlatformCommon.product_id == Product.id)
                & (PlatformCommon.platform_name == 'vr')
            )
            .where(func.lower(Product.brand) == brand_value)
        )

        pending_rows = await self.db.execute(pending_stmt)
        for product, platform_common in pending_rows.all():
            if product.id in seen_product_ids:
                continue

            if platform_common:
                if platform_common.sync_status == SyncStatus.SYNCED.value:
                    continue
                if platform_common.external_id and platform_common.external_id not in (None, '', product.sku):
                    continue
            candidates.append((product, platform_common))
            seen_product_ids.add(product.id)

        if not candidates:
            return None

        candidate_ids = [product.id for product, _ in candidates]
        other_counts: Dict[int, int] = {}
        if candidate_ids:
            other_stmt = (
                select(PlatformCommon.product_id, func.count())
                .where(
                    PlatformCommon.product_id.in_(candidate_ids),
                    PlatformCommon.platform_name != 'vr'
                )
                .group_by(PlatformCommon.product_id)
            )
            other_counts = {pid: count for pid, count in (await self.db.execute(other_stmt)).all()}

        best_match = None
        best_score = 0
        def _normalize(text: Optional[str]) -> str:
            return (text or '').lower().strip()

        for product, platform_common in candidates:
            score = 0
            reasons: List[str] = []

            product_brand = _normalize(product.brand)
            product_model = _normalize(product.model)
            product_finish = _normalize(product.finish)
            product_year = str(product.year or '').strip()

            # Brand match is mandatory
            if product_brand and product_brand == brand_value:
                score += 35
                reasons.append('brand')
            else:
                continue

            if model_value and product_model:
                if product_model == model_value:
                    score += 30
                    reasons.append('model')

            if finish_value and product_finish and product_finish == finish_value:
                score += 5
                reasons.append('finish')

            if year_value and product_year:
                if product_year == year_value:
                    score += 10
                    reasons.append('year')
                elif year_value.endswith('s') and product_year.startswith(year_value[:3]):
                    score += 6
                    reasons.append('decade')

            base_price = product.base_price or product.price or 0
            expected_vr_price = round(base_price * 1.05) if base_price else 0
            if price_value > 0 and expected_vr_price > 0:
                price_ratio = abs(price_value - expected_vr_price) / max(price_value, expected_vr_price)
                if price_ratio <= 0.03:
                    score += 10
                    reasons.append('price')
                elif price_ratio <= 0.06:
                    score += 6
                    reasons.append('price_close')

            if description_value and product.description:
                product_desc = product.description.lower()
                if product.sku and product.sku.lower() in description_value:
                    score += 15
                    reasons.append('sku_in_description')
                else:
                    ratio = SequenceMatcher(None, product_desc[:200], description_value[:200]).ratio()
                    if ratio >= 0.4:
                        score += 8
                        reasons.append('description')

            # Bonus if product already has other platforms but VR pending
            other_platforms = other_counts.get(product.id, 0)
            if other_platforms and (not platform_common or not platform_common.external_id or platform_common.external_id in ('', product.sku)):
                score += 5
                reasons.append('platform_gap')

            if score > best_score:
                best_score = score
                best_match = {
                    "product": product,
                    "platform_common": platform_common,
                    "score": min(score / 100.0, 1.0),
                    "reason": ", ".join(reasons)
                }

        if best_match and best_score >= 60:
            return best_match

        return None
    
    async def _detect_removed_listings(
        self, 
        platform: str, 
        platform_lookup: Dict, 
        local_lookup: Dict
    ) -> List[DetectedChange]:
        """Detect listings that were removed from platform"""
        changes = []
        
        for external_id, local_item in local_lookup.items():
            if external_id not in platform_lookup:
                # This listing exists locally but not on platform
                changes.append(DetectedChange(
                    platform=platform,
                    external_id=external_id,
                    product_id=local_item.get('product_id'),
                    sku=local_item.get('sku', 'unknown'),
                    change_type="removed_listing",
                    field="listing",
                    old_value=local_item.get('title', 'Removed listing'),
                    new_value=None,
                    requires_propagation=True  # Might need to propagate removal
                ))
        
        return changes
    
    def _should_propagate_status_change(self, new_status: str, old_status: str) -> bool:
        """Determine if a status change should be propagated to other platforms"""
        # Definitely propagate sales and endings
        if new_status.lower() in ['sold', 'ended', 'completed', 'inactive']:
            return True
        # Propagate going from sold back to active (suspicious, but handle it)
        if old_status.lower() in ['sold', 'ended'] and new_status.lower() in ['active', 'live']:
            return True
        # Don't propagate minor status changes
        return False


class InboundSyncScheduler:
    """Coordinates periodic platform data fetching and comparison"""
    
    def __init__(self, db: AsyncSession, report_only: bool = True):
        self.db = db
        self.report_only = report_only
        self.change_detector = ChangeDetector(db)
    
    async def run_platform_sync(self, platform: str) -> SyncReport:
        """
        Run sync for a single platform
        
        Args:
            platform: Platform name (ebay, reverb, shopify, vr)
            
        Returns:
            SyncReport with detected changes
        """
        logger.info(f"Starting {'report-only' if self.report_only else 'full'} sync for {platform}")
        
        try:
            # Fetch current platform data using existing services
            platform_data = await self._fetch_platform_data(platform)
            
            # Detect changes
            report = await self.change_detector.detect_platform_changes(platform, platform_data)
            
            if not self.report_only and report.changes_detected:
                # Future: Apply changes to database and trigger propagation
                logger.info(f"Would apply {len(report.changes_detected)} changes (report_only=False not implemented yet)")
            
            return report
            
        except Exception as e:
            logger.exception(f"Error during platform sync for {platform}")
            return SyncReport(
                platform=platform,
                timestamp=datetime.now(),
                total_platform_items=0,
                total_local_items=0,
                changes_detected=[],
                errors=[f"Sync error: {str(e)}"],
                processing_time_seconds=0
            )
    
    async def run_all_platforms_sync(self) -> Dict[str, SyncReport]:
        """Run sync for all platforms and return comprehensive report"""
        platforms = ["ebay", "reverb", "shopify", "vr"]
        reports = {}
        
        for platform in platforms:
            try:
                reports[platform] = await self.run_platform_sync(platform)
            except Exception as e:
                logger.exception(f"Failed to sync {platform}")
                reports[platform] = SyncReport(
                    platform=platform,
                    timestamp=datetime.now(),
                    total_platform_items=0,
                    total_local_items=0,
                    changes_detected=[],
                    errors=[f"Platform sync failed: {str(e)}"],
                    processing_time_seconds=0
                )
        
        return reports
    
    async def _fetch_platform_data(self, platform: str) -> List[Dict[str, Any]]:
        """Fetch current data from platform using existing service clients"""
        
        if platform == "ebay":
            from app.services.ebay_service import EbayService
            ebay_service = EbayService(self.db)
            # Use existing method to get all listings
            return await ebay_service.get_all_active_listings()  # You'll need to implement this method
            
        elif platform == "reverb":
            from app.services.reverb.client import ReverbClient
            reverb_client = ReverbClient()
            # Use existing method
            listings = await reverb_client.get_all_listings_detailed()
            return [listing.__dict__ if hasattr(listing, '__dict__') else listing for listing in listings]
            
        elif platform == "shopify":
            from app.services.shopify.client import ShopifyClient
            shopify_client = ShopifyClient()
            # Use existing method
            products = await shopify_client.get_all_products_summary()
            return products
            
        elif platform == "vr":
            from app.services.vr_service import VRService
            vr_service = VRService(self.db)
            # Use existing CSV download method
            df = await vr_service.download_inventory_dataframe()
            return df.to_dict('records') if df is not None else []
            
        else:
            raise ValueError(f"Unknown platform: {platform}")

    def print_sync_report(self, report: SyncReport) -> None:
        """Print a human-readable sync report"""
        print(f"\n{'='*60}")
        print(f"SYNC REPORT: {report.platform.upper()}")
        print(f"{'='*60}")
        print(f"Timestamp: {report.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Processing Time: {report.processing_time_seconds:.2f} seconds")
        print(f"Platform Items: {report.total_platform_items}")
        print(f"Local Items: {report.total_local_items}")
        
        if report.errors:
            print(f"\n❌ ERRORS ({len(report.errors)}):")
            for error in report.errors:
                print(f"  • {error}")
        
        if report.changes_detected:
            print(f"\n📊 CHANGES DETECTED ({len(report.changes_detected)}):")
            
            # Group by change type
            by_type = report.changes_by_type
            for change_type, count in by_type.items():
                print(f"  • {change_type}: {count}")
            
            print(f"\n📋 DETAILED CHANGES:")
            for change in report.changes_detected[:10]:  # Show first 10
                propagate = "🔄" if change.requires_propagation else "ℹ️"
                print(f"  {propagate} {change.change_type.upper()}: {change.sku}")
                print(f"     {change.field}: {change.old_value} → {change.new_value}")
                if change.metadata:
                    print(f"     info: {change.metadata}")
                
            if len(report.changes_detected) > 10:
                print(f"     ... and {len(report.changes_detected) - 10} more changes")
        else:
            print("\n✅ NO CHANGES DETECTED")
        
        print(f"{'='*60}\n")


# Helper function for fastAPI dependency injection
async def get_sync_service(
    db: AsyncSession,
    request = None
) -> SyncService:
    """
    Create a SyncService with database session and stock manager from app state.
    
    Args:
        db: Database session from dependency
        request: Optional FastAPI request object
        
    Returns:
        Configured SyncService instance
    """
    stock_manager = None
    if request and hasattr(request.app.state, 'stock_manager'):
        stock_manager = request.app.state.stock_manager
    
    return SyncService(db, stock_manager)
