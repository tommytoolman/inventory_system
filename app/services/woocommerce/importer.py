# app/services/woocommerce/importer.py
"""
WooCommerce Importer Service - handles bulk import of WooCommerce products into database.
Follows the same pattern as ShopifyImporter.
"""

import logging
import uuid as uuid_mod
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.enums import SyncStatus, ListingStatus
from app.models.woocommerce import WooCommerceListing
from app.models.platform_common import PlatformCommon
from app.models.product import Product
from app.models.sync_event import SyncEvent
from app.services.woocommerce.client import WooCommerceClient
from app.services.woocommerce.errors import (
    WCAuthenticationError, WCConnectionError, WCDataTransformError, WCAPIError,
)
from app.services.woocommerce.error_logger import wc_logger
from app.services.woocommerce.error_tracker import WCErrorTracker

logger = logging.getLogger(__name__)


class WooCommerceImporter:
    """
    WooCommerce importer service that handles bulk import of WooCommerce products.
    Populates: woocommerce_listings, platform_common, and products tables.

    Accepts an optional ``wc_store`` for multi-tenant operation.
    When omitted, falls back to global env-var credentials (single-tenant).
    """

    def __init__(self, db_session: AsyncSession, wc_store=None):
        """Initialize with database session and optional store context."""
        self.session = db_session
        self.wc_store = wc_store
        self._wc_store_id = wc_store.id if wc_store else None

        # Build client from store credentials or fall back to env vars
        if wc_store:
            self.client = WooCommerceClient(
                store_url=wc_store.store_url,
                consumer_key=wc_store.consumer_key,
                consumer_secret=wc_store.consumer_secret,
            )
        else:
            self.client = WooCommerceClient()

        self._sync_run_id: Optional[uuid_mod.UUID] = None
        self._processed_wc_ids: set = set()
        # Batch-loaded existing listings lookup (WC-P3-038: N+1 fix)
        self._existing_listings: Optional[Dict[str, WooCommerceListing]] = None

    async def close(self):
        """Close the underlying HTTP client."""
        await self.client.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def import_all_listings(self, status_filter: Optional[str] = None,
                                  limit: Optional[int] = None,
                                  sync_run_id: str = None) -> Dict[str, Any]:
        """
        Import all WooCommerce products from API to database.

        Args:
            status_filter: Only import products with this status (publish, draft, etc.)
            limit: Max number of products to import
            sync_run_id: UUID string to correlate logs for this run

        Returns:
            Statistics dict with counts and optional error_summary
        """
        run_id = sync_run_id or "manual"
        # Store sync_run_id as UUID for SyncEvent creation
        try:
            self._sync_run_id = uuid_mod.UUID(run_id) if run_id != "manual" else uuid_mod.uuid4()
        except (ValueError, AttributeError):
            self._sync_run_id = uuid_mod.uuid4()
        self._processed_wc_ids = set()

        logger.info("Starting WooCommerce product import")
        wc_logger.sync_start(run_id, "Product Import")
        start_time = datetime.now()

        stats: Dict[str, Any] = {
            "total": 0,
            "created": 0,
            "updated": 0,
            "sku_matched": 0,
            "errors": 0,
            "skipped": 0,
        }
        error_tracker = WCErrorTracker(sync_run_id=run_id)

        try:
            # WC-P3-038: Pre-load all existing WC listings into memory to avoid N+1 queries
            wc_logger.sync_progress("Pre-loading existing WC listings from database...")
            await self._batch_load_existing_listings()

            # Fetch all products from WooCommerce
            wc_logger.sync_progress("Fetching products from WooCommerce API...")
            wc_products = await self.client.get_all_products()

            if limit:
                wc_products = wc_products[:limit]

            wc_logger.sync_progress(
                f"Retrieved {len(wc_products)} products from API"
            )
            stats["total"] = len(wc_products)

            for i, product_data in enumerate(wc_products, 1):
                try:
                    if i % 50 == 0:
                        wc_logger.sync_progress(
                            f"Progress: {i}/{len(wc_products)} processed"
                        )

                    # Apply status filter
                    product_status = product_data.get("status", "")
                    if status_filter and product_status != status_filter:
                        stats["skipped"] += 1
                        continue

                    result = await self._process_single_product(product_data)
                    stats[result] += 1

                except (WCAuthenticationError, WCConnectionError) as e:
                    # Critical -- abort entire import
                    error_tracker.record(e)
                    wc_logger.log_error(e)
                    wc_logger.sync_error(run_id, e)
                    await self.session.rollback()
                    raise

                except Exception as e:
                    # Non-critical -- log and continue with next product
                    wc_id = str(product_data.get("id", "?"))
                    wc_sku = product_data.get("sku", "")

                    if hasattr(e, "to_dict"):
                        # Already a structured WC exception
                        error_tracker.record(e)
                        wc_logger.log_error(e)
                    else:
                        # Wrap generic exception with product context
                        wrapped = WCDataTransformError(
                            str(e),
                            operation="import_product",
                            wc_product_id=wc_id,
                            sku=wc_sku,
                        )
                        error_tracker.record(wrapped)
                        wc_logger.log_error(wrapped)

                    wc_logger.sync_warning(
                        f"WC#{wc_id} ({wc_sku}): {str(e)[:120]}"
                    )
                    stats["errors"] += 1

            # Detect removed listings: products in DB but not in API response
            await self._detect_removed_listings()

            await self.session.commit()

            elapsed = (datetime.now() - start_time).total_seconds()
            error_summary = (
                error_tracker.get_summary()
                if error_tracker.error_count > 0
                else None
            )

            wc_logger.sync_complete(
                run_id, stats,
                error_summary=error_summary,
                duration_seconds=elapsed,
            )
            logger.info(
                f"WooCommerce import completed in {elapsed:.1f}s - "
                f"Total: {stats['total']}, Created: {stats['created']}, "
                f"Updated: {stats['updated']}, SKU matched: {stats['sku_matched']}, "
                f"Errors: {stats['errors']}"
            )

        except (WCAuthenticationError, WCConnectionError):
            raise  # Already logged above

        except Exception as e:
            elapsed = (datetime.now() - start_time).total_seconds()
            wc_logger.log_error(
                WCAPIError(str(e), operation="import_all_listings")
            )
            wc_logger.sync_error(run_id, e)
            logger.error(f"WooCommerce import failed: {e}", exc_info=True)
            await self.session.rollback()
            raise

        # Attach error summary to stats for the caller
        if error_tracker.error_count > 0:
            stats["error_summary"] = error_tracker.get_summary()

        return stats

    async def _process_single_product(self, wc_data: Dict[str, Any]) -> str:
        """
        Process a single WooCommerce product into the database.

        Returns one of: 'created', 'updated', 'sku_matched'
        """
        wc_product_id = str(wc_data["id"])
        wc_sku = wc_data.get("sku", "")
        self._processed_wc_ids.add(wc_product_id)

        # Warn about unsupported product types
        product_type = wc_data.get("type", "simple")
        if product_type in ("variable", "grouped", "external"):
            logger.warning(
                f"WooCommerce product {wc_product_id} is type '{product_type}' "
                f"— imported as simple product. Variations not supported."
            )

        # Extract data for our tables
        product_info = self._extract_product_data(wc_data)
        listing_info = self._extract_listing_data(wc_data)
        platform_info = self._extract_platform_common_data(wc_data)

        # Check if WooCommerceListing already exists for this WC product
        existing_listing = await self._find_existing_listing(wc_product_id)

        if existing_listing:
            # Detect changes before updating
            await self._detect_and_record_changes(existing_listing, listing_info, wc_product_id)
            # UPDATE existing listing
            await self._update_existing(existing_listing, listing_info, platform_info, wc_data)
            return "updated"

        # Check if a Product with matching SKU already exists (cross-platform link)
        # NOTE: IntegrityError handling covers the race condition where a concurrent
        # webhook + sync both try to create a listing for the same WC product.
        # A proper UNIQUE constraint on woocommerce_listings.wc_product_id should
        # be added via Alembic migration as a follow-up.
        if wc_sku:
            existing_product = await self._find_product_by_sku(wc_sku)
            if existing_product:
                try:
                    await self._create_listing_for_existing_product(
                        existing_product, listing_info, platform_info, wc_data
                    )
                    await self.session.flush()
                except IntegrityError:
                    await self.session.rollback()
                    logger.warning(
                        f"IntegrityError for WC product {wc_product_id} (SKU match) — "
                        f"concurrent process likely created it; falling back to update"
                    )
                    refetched = await self._find_existing_listing(wc_product_id)
                    if refetched:
                        await self._update_existing(refetched, listing_info, platform_info, wc_data)
                        return "updated"
                # Create SyncEvent for new listing (SKU match)
                await self._create_sync_event(
                    product_id=existing_product.id,
                    external_id=wc_product_id,
                    change_type="new_listing",
                    change_data={"source": "sku_match", "sku": wc_sku},
                )
                logger.info(f"SKU MATCH: WC product {wc_product_id} → existing product SKU {wc_sku}")
                return "sku_matched"

        # CREATE new Product + PlatformCommon + WooCommerceListing
        try:
            await self._create_new(product_info, listing_info, platform_info, wc_data)
        except IntegrityError:
            await self.session.rollback()
            logger.warning(
                f"IntegrityError for WC product {wc_product_id} — "
                f"concurrent process likely created it; falling back to update"
            )
            refetched = await self._find_existing_listing(wc_product_id)
            if refetched:
                await self._update_existing(refetched, listing_info, platform_info, wc_data)
                return "updated"
        return "created"

    # ------------------------------------------------------------------
    # Data extraction helpers
    # ------------------------------------------------------------------

    def _extract_product_data(self, wc_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract RIFF Product fields from WooCommerce data."""
        images = wc_data.get("images", [])
        primary_image = images[0]["src"] if images else None
        additional_images = [img["src"] for img in images[1:]] if len(images) > 1 else []

        # Extract brand from attributes or meta
        brand = ""
        model_name = ""
        for attr in wc_data.get("attributes", []):
            name_lower = attr.get("name", "").lower()
            if name_lower == "brand":
                options = attr.get("options", [])
                brand = options[0] if options else ""
            elif name_lower == "model":
                options = attr.get("options", [])
                model_name = options[0] if options else ""

        # Use effective price first (reflects sale price when active), then regular_price
        price_str = wc_data.get("price") or wc_data.get("regular_price") or ""
        if not price_str or str(price_str).strip() == "":
            wc_logger.log_warning(
                f"WooCommerce product {wc_data.get('id')} has no price set — "
                f"defaulting to 0.00. This product may need manual pricing "
                f"before publishing to other platforms.",
                operation="import_product",
                wc_product_id=str(wc_data.get("id", "")),
            )
            price_str = "0"
        try:
            price = float(price_str)
        except (ValueError, TypeError):
            price = 0.0
            wc_logger.log_warning(
                f"Could not parse price '{price_str}' for WC product "
                f"{wc_data.get('id')} -- defaulted to 0",
                operation="import_product",
                wc_product_id=str(wc_data.get("id", "")),
            )

        return {
            "sku": wc_data.get("sku") or f"WC-{wc_data['id']}",
            "title": wc_data.get("name", ""),
            "brand": brand,
            "model": model_name,
            "description": wc_data.get("description", ""),
            "base_price": price,
            "quantity": wc_data.get("stock_quantity") if wc_data.get("stock_quantity") is not None else 1,
            "primary_image": primary_image,
            "additional_images": additional_images,
            "category": self._extract_category_name(wc_data),
        }

    def _extract_listing_data(self, wc_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract WooCommerceListing-specific fields."""
        price_str = wc_data.get("price") or wc_data.get("regular_price") or "0"
        regular_str = wc_data.get("regular_price") or "0"
        sale_str = wc_data.get("sale_price") or None

        try:
            price = float(price_str)
        except (ValueError, TypeError):
            price = 0.0
        try:
            regular_price = float(regular_str)
        except (ValueError, TypeError):
            regular_price = 0.0
        try:
            sale_price = float(sale_str) if sale_str else None
        except (ValueError, TypeError):
            sale_price = None

        # Parse WC timestamps
        wc_created = self._parse_wc_datetime(wc_data.get("date_created"))
        wc_modified = self._parse_wc_datetime(wc_data.get("date_modified"))

        categories = wc_data.get("categories", [])
        cat_id = str(categories[0]["id"]) if categories else None
        cat_name = categories[0].get("name") if categories else None

        return {
            "wc_product_id": str(wc_data["id"]),
            "slug": wc_data.get("slug"),
            "permalink": wc_data.get("permalink"),
            "title": wc_data.get("name"),
            "status": wc_data.get("status"),
            "product_type": wc_data.get("type"),
            "sku": wc_data.get("sku"),
            "price": price,
            "regular_price": regular_price,
            "sale_price": sale_price,
            "manage_stock": wc_data.get("manage_stock", False),
            "stock_quantity": wc_data.get("stock_quantity"),
            "stock_status": wc_data.get("stock_status"),
            "category_id": cat_id,
            "category_name": cat_name,
            "weight": wc_data.get("weight"),
            "shipping_class": wc_data.get("shipping_class"),
            "total_sales": wc_data.get("total_sales", 0),
            "wc_created_at": wc_created,
            "wc_modified_at": wc_modified,
        }

    def _extract_platform_common_data(self, wc_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract PlatformCommon fields."""
        status_map = {
            "publish": ListingStatus.ACTIVE.value,
            "draft": ListingStatus.DRAFT.value,
            "pending": ListingStatus.DRAFT.value,
            "private": ListingStatus.ACTIVE.value,
            "trash": ListingStatus.DELETED.value,
        }
        wc_status = wc_data.get("status", "draft")
        internal_status = status_map.get(wc_status, ListingStatus.DRAFT.value)

        return {
            "platform_name": "woocommerce",
            "external_id": str(wc_data["id"]),
            "status": internal_status,
            "sync_status": SyncStatus.SYNCED.value,
            "listing_url": wc_data.get("permalink"),
            "platform_specific_data": {
                "price": wc_data.get("price"),
                "currency": "GBP",
                "stock_quantity": wc_data.get("stock_quantity"),
                "stock_status": wc_data.get("stock_status"),
            },
        }

    def _extract_category_name(self, wc_data: Dict[str, Any]) -> str:
        """Extract primary category name."""
        categories = wc_data.get("categories", [])
        if categories:
            return categories[0].get("name", "Uncategorised")
        return "Uncategorised"

    def _parse_wc_datetime(self, dt_str: Optional[str]) -> Optional[datetime]:
        """Parse WooCommerce datetime string to naive UTC datetime."""
        if not dt_str:
            return None
        try:
            # WC returns ISO 8601: "2024-01-15T10:30:00"
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            if dt.tzinfo:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except (ValueError, TypeError):
            return None

    # ------------------------------------------------------------------
    # Change detection and SyncEvent creation
    # ------------------------------------------------------------------

    async def _detect_and_record_changes(
        self, existing: WooCommerceListing, new_data: Dict, wc_product_id: str
    ) -> None:
        """Compare existing listing against new data and create SyncEvents for changes."""
        product_id = None
        platform_common_id = None
        if existing.platform_id:
            pc_result = await self.session.execute(
                select(PlatformCommon).where(PlatformCommon.id == existing.platform_id)
            )
            pc = pc_result.scalar_one_or_none()
            if pc:
                product_id = pc.product_id
                platform_common_id = pc.id

        # Price change
        old_price = existing.price or 0.0
        new_price = new_data.get("price", 0.0)
        if abs(old_price - new_price) > 0.01:
            await self._create_sync_event(
                product_id=product_id,
                platform_common_id=platform_common_id,
                external_id=wc_product_id,
                change_type="price_change",
                change_data={"old": str(old_price), "new": str(new_price)},
            )

        # Quantity change
        old_qty = existing.stock_quantity
        new_qty = new_data.get("stock_quantity")
        if old_qty != new_qty and new_qty is not None:
            await self._create_sync_event(
                product_id=product_id,
                platform_common_id=platform_common_id,
                external_id=wc_product_id,
                change_type="quantity_change",
                change_data={"old": str(old_qty), "new": str(new_qty)},
            )

        # Status change
        old_status = existing.status
        new_status = new_data.get("status")
        if old_status != new_status and new_status is not None:
            await self._create_sync_event(
                product_id=product_id,
                platform_common_id=platform_common_id,
                external_id=wc_product_id,
                change_type="status_change",
                change_data={"old": old_status, "new": new_status},
            )

    async def _detect_removed_listings(self) -> None:
        """Find WC listings in DB that were not in the API response and create SyncEvents."""
        if not self._processed_wc_ids:
            return

        result = await self.session.execute(
            select(WooCommerceListing).where(
                WooCommerceListing.status != "trash",
            )
        )
        all_listings = result.scalars().all()

        for listing in all_listings:
            if listing.wc_product_id and listing.wc_product_id not in self._processed_wc_ids:
                product_id = None
                platform_common_id = None
                if listing.platform_id:
                    pc_result = await self.session.execute(
                        select(PlatformCommon).where(PlatformCommon.id == listing.platform_id)
                    )
                    pc = pc_result.scalar_one_or_none()
                    if pc:
                        product_id = pc.product_id
                        platform_common_id = pc.id

                await self._create_sync_event(
                    product_id=product_id,
                    platform_common_id=platform_common_id,
                    external_id=listing.wc_product_id,
                    change_type="removed_listing",
                    change_data={"title": listing.title, "sku": listing.sku},
                    notes="Listing exists in DB but was not returned by WooCommerce API",
                )

    async def _create_sync_event(
        self,
        external_id: str,
        change_type: str,
        change_data: Dict[str, Any],
        product_id: Optional[int] = None,
        platform_common_id: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> None:
        """Create a SyncEvent record for a detected change."""
        event = SyncEvent(
            sync_run_id=self._sync_run_id,
            platform_name="woocommerce",
            product_id=product_id,
            platform_common_id=platform_common_id,
            external_id=external_id,
            change_type=change_type,
            change_data=change_data,
            status="pending",
            notes=notes,
        )
        self.session.add(event)

    # ------------------------------------------------------------------
    # Database operations
    # ------------------------------------------------------------------

    async def _batch_load_existing_listings(self) -> None:
        """Pre-load all existing WC listings into a lookup dict (WC-P3-038).

        Reduces N+1 queries (1 SELECT per product) to a single query.
        """
        stmt = select(WooCommerceListing)
        store_id = getattr(self, "_wc_store_id", None)
        if store_id is not None:
            stmt = stmt.where(WooCommerceListing.wc_store_id == store_id)
        result = await self.session.execute(stmt)
        all_listings = result.scalars().all()
        self._existing_listings = {
            listing.wc_product_id: listing
            for listing in all_listings
            if listing.wc_product_id
        }
        logger.info(f"Pre-loaded {len(self._existing_listings)} existing WC listings")

    async def _find_existing_listing(self, wc_product_id: str) -> Optional[WooCommerceListing]:
        """Find existing WooCommerceListing by WC product ID.

        Uses the pre-loaded dict if available (bulk import), otherwise
        falls back to a single SELECT (webhook / single-product import).
        """
        if getattr(self, "_existing_listings", None) is not None:
            return self._existing_listings.get(wc_product_id)
        result = await self.session.execute(
            select(WooCommerceListing).where(
                WooCommerceListing.wc_product_id == wc_product_id
            )
        )
        return result.scalar_one_or_none()

    async def _find_product_by_sku(self, sku: str) -> Optional[Product]:
        """Find existing Product by SKU."""
        result = await self.session.execute(
            select(Product).where(Product.sku == sku)
        )
        return result.scalar_one_or_none()

    async def _update_existing(self, existing_listing: WooCommerceListing,
                               listing_info: Dict, platform_info: Dict,
                               wc_data: Dict) -> None:
        """Update an existing WooCommerceListing and its PlatformCommon."""
        # Update listing fields
        for key, value in listing_info.items():
            if hasattr(existing_listing, key) and value is not None:
                setattr(existing_listing, key, value)

        existing_listing.extended_attributes = wc_data
        existing_listing.last_synced_at = datetime.now(timezone.utc).replace(tzinfo=None)

        # Update PlatformCommon
        if existing_listing.platform_id:
            pc_result = await self.session.execute(
                select(PlatformCommon).where(PlatformCommon.id == existing_listing.platform_id)
            )
            platform_common = pc_result.scalar_one_or_none()
            if platform_common:
                platform_common.status = platform_info["status"]
                platform_common.sync_status = SyncStatus.SYNCED.value
                platform_common.listing_url = platform_info.get("listing_url")
                platform_common.platform_specific_data = platform_info.get("platform_specific_data", {})
                platform_common.last_sync = datetime.now(timezone.utc).replace(tzinfo=None)

    async def _create_listing_for_existing_product(self, product: Product,
                                                   listing_info: Dict,
                                                   platform_info: Dict,
                                                   wc_data: Dict) -> None:
        """Create WooCommerceListing + PlatformCommon for an existing Product (SKU match)."""
        # Check if PlatformCommon already exists for this product+platform (prevent duplicates)
        existing_pc = await self.session.execute(
            select(PlatformCommon).where(
                PlatformCommon.product_id == product.id,
                PlatformCommon.platform_name == "woocommerce",
            )
        )
        platform_common = existing_pc.scalar_one_or_none()

        if platform_common:
            # Update existing PlatformCommon instead of creating new
            platform_common.external_id = platform_info["external_id"]
            platform_common.status = platform_info["status"]
            platform_common.sync_status = platform_info["sync_status"]
            platform_common.listing_url = platform_info.get("listing_url")
            platform_common.platform_specific_data = platform_info.get("platform_specific_data", {})
            platform_common.last_sync = datetime.now(timezone.utc).replace(tzinfo=None)
        else:
            # Create new PlatformCommon
            platform_common = PlatformCommon(
                product_id=product.id,
                last_sync=datetime.now(timezone.utc).replace(tzinfo=None),
                **platform_info,
            )
            self.session.add(platform_common)
            await self.session.flush()

        # Create WooCommerceListing
        wc_listing = WooCommerceListing(
            platform_id=platform_common.id,
            wc_store_id=getattr(self, "_wc_store_id", None),
            extended_attributes=wc_data,
            last_synced_at=datetime.now(timezone.utc).replace(tzinfo=None),
            **listing_info,
        )
        self.session.add(wc_listing)

    async def _create_new(self, product_info: Dict, listing_info: Dict,
                          platform_info: Dict, wc_data: Dict) -> None:
        """Create a new Product + PlatformCommon + WooCommerceListing."""
        # Create Product
        product = Product(
            sku=product_info["sku"],
            title=product_info.get("title"),
            brand=product_info.get("brand"),
            model=product_info.get("model"),
            description=product_info.get("description"),
            base_price=product_info.get("base_price"),
            quantity=product_info.get("quantity", 1),
            primary_image=product_info.get("primary_image"),
            additional_images=product_info.get("additional_images", []),
            category=product_info.get("category"),
        )
        self.session.add(product)
        await self.session.flush()

        # Create PlatformCommon
        platform_common = PlatformCommon(
            product_id=product.id,
            last_sync=datetime.now(timezone.utc).replace(tzinfo=None),
            **platform_info,
        )
        self.session.add(platform_common)
        await self.session.flush()

        # Create WooCommerceListing
        wc_listing = WooCommerceListing(
            platform_id=platform_common.id,
            wc_store_id=getattr(self, "_wc_store_id", None),
            extended_attributes=wc_data,
            last_synced_at=datetime.now(timezone.utc).replace(tzinfo=None),
            **listing_info,
        )
        self.session.add(wc_listing)
