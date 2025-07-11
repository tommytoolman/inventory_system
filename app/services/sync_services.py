# app/services/sync_service.py
"""
Central service for synchronizing products across multiple platforms.

This service coordinates:
1. Stock level synchronization across platforms
2. Platform-specific listing creation/updates
3. Status tracking and error handling
4. Reconciliation of detected changes from all platforms.
"""

import logging

from typing import Dict, List, Any, Optional, Set, NamedTuple
from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.platform_common import PlatformCommon
from app.models.sync_event import SyncEvent
from app.core.enums import SyncStatus, ListingStatus

# Import platform services for outbound actions
from app.services.vintageandrare_service import VintageAndRareService
# from app.services.ebay_service import EbayService
# from app.services.reverb_service import ReverbService
from app.integrations.events import StockUpdateEvent

logger = logging.getLogger(__name__)

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

class SyncService:
    """
    Coordinates synchronization between inventory system and external platforms.
    
    This service:
    1. Acts as a facade over the StockManager
    2. Maintains platform sync status data
    3. Handles platform-specific synchronization logic
    """
    
    def __init__(self, db: AsyncSession, stock_manager=None):
        """
        Initialize the sync service with database session and optional stock manager.
        
        Args:
            db: AsyncSession for database operations
            stock_manager: StockManager instance from app state
        """
        self.db = db
        self.stock_manager = stock_manager
        
        # Instantiate other services for outbound actions. This makes SyncService a true orchestrator.
        self.platform_services = {
            "vr": VintageAndRareService(db),
            # "ebay": EbayService(db),
            # "reverb": ReverbService(db),
        }

    async def reconcile_sync_run(self, sync_run_id: str) -> Dict[str, Any]:
        """
        Phase 2 of the sync process.
        Processes all 'pending' SyncEvent records for a given run, resolves conflicts,
        and triggers the necessary cross-platform actions.
        """
        logger.info(f"Starting reconciliation for sync_run_id: {sync_run_id}")
        report = {"processed": 0, "actions_taken": 0, "errors": 0}

        # 1. Fetch all pending events for this run
        stmt = select(SyncEvent).where(
            SyncEvent.sync_run_id == sync_run_id,
            SyncEvent.status == 'pending'
        ).order_by(SyncEvent.detected_at)
        
        result = await self.db.execute(stmt)
        events = result.scalars().all()
        logger.info(f"Found {len(events)} pending events to reconcile.")
        
        # 2. Group events by product_id to handle conflicts (e.g., sold on two platforms at once)
        events_by_product: Dict[int, List[SyncEvent]] = {}
        for event in events:
            if event.product_id:
                events_by_product.setdefault(event.product_id, []).append(event)

        # 3. Process events product by product
        for product_id, product_events in events_by_product.items():
            try:
                # Find the "winning" event. For sales, the first one detected wins.
                sold_event = next((e for e in product_events if e.change_type == 'status' and e.change_data.get('new', '').upper() == 'SOLD'), None)

                if sold_event:
                    logger.info(f"Processing 'sold' event for product {sold_event.product_id} from {sold_event.platform_name}")
                    
                    # To propagate the sale, we need the external_ids for this product on OTHER platforms.
                    platform_links_stmt = select(PlatformCommon).where(
                        PlatformCommon.product_id == product_id,
                        PlatformCommon.platform_name != sold_event.platform_name # Exclude the source platform
                    )
                    platform_links_result = await self.db.execute(platform_links_stmt)
                    other_platform_links = platform_links_result.scalars().all()

                    # Propagate the 'sold' status to all other platforms
                    for link in other_platform_links:
                        service = self.platform_services.get(link.platform_name)
                        if service and hasattr(service, 'mark_item_as_sold'):
                            logger.info(f"Telling {link.platform_name.upper()} to mark item {link.external_id} as sold.")
                            try:
                                success = await service.mark_item_as_sold(link.external_id)
                                if not success:
                                    logger.error(f"Failed to mark item {link.external_id} as sold on {link.platform_name.upper()}.")
                                    # You might want to log this failure to the event notes
                            except Exception as service_exc:
                                logger.error(f"Exception calling mark_item_as_sold for {link.platform_name.upper()}: {service_exc}", exc_info=True)
                        else:
                            logger.warning(f"No 'mark_item_as_sold' method found for service '{link.platform_name}'.")

                    report["actions_taken"] += 1
                
                # Mark all events for this product as processed
                for e in product_events:
                    e.status = 'processed'
                    e.processed_at = datetime.now(timezone.utc)
                    report["processed"] += 1

            except Exception as e:
                logger.error(f"Error reconciling events for product {product_id}: {e}", exc_info=True)
                for e_event in product_events:
                    e_event.status = 'error'
                    e_event.notes = str(e)
                    e_event.processed_at = datetime.now(timezone.utc)
                report["errors"] += 1
        
        await self.db.commit()
        logger.info(f"Reconciliation complete for {sync_run_id}. Report: {report}")
        return report
    
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
                           el.current_price, el.listing_status
                    FROM platform_common pc
                    JOIN products p ON pc.product_id = p.id
                    LEFT JOIN ebay_listings el ON pc.external_id = el.ebay_item_id
                    WHERE pc.platform_name = 'ebay'
                """)
            elif platform == "reverb":
                query = text("""
                    SELECT pc.external_id, pc.product_id, pc.status, pc.last_sync,
                           p.sku, p.brand, p.model, p.title, p.base_price,
                           rl.price_display, rl.reverb_state
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
            if platform_status and local_status and platform_status != local_status:
                changes.append(DetectedChange(
                    platform=platform,
                    external_id=external_id,
                    product_id=local_item.get('product_id'),
                    sku=local_item.get('sku', 'unknown'),
                    change_type="status_change",
                    field="status",
                    old_value=local_status,
                    new_value=platform_status,
                    requires_propagation=self._should_propagate_status_change(platform_status, local_status)
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
            
            # Get local price
            local_price = local_item.get('base_price')
            
            # Compare prices (with tolerance for floating point)
            if platform_price and local_price:
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
            if external_id not in local_lookup:
                # This is a new listing not in our system
                changes.append(DetectedChange(
                    platform=platform,
                    external_id=external_id,
                    product_id=None,
                    sku=platform_item.get('sku', 'unknown'),
                    change_type="new_listing",
                    field="listing",
                    old_value=None,
                    new_value=platform_item.get('title', 'New listing'),
                    requires_propagation=False  # Don't propagate new unknown listings
                ))
        
        return changes
    
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
            from app.services.vintageandrare_service import VintageAndRareService
            vr_service = VintageAndRareService(self.db)
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