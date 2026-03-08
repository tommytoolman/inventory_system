# app/services/woocommerce_service.py
"""
WooCommerce Service - high-level business logic and sync orchestration.

Follows the same facade pattern as ShopifyService / ReverbService.
Coordinates between WooCommerceClient, WooCommerceImporter, and the database.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.core.config import Settings, get_settings
from app.core.enums import SyncStatus, ListingStatus
from app.core.exceptions import WooCommerceAPIError
from app.services.pricing import calculate_platform_price
from app.models.product import Product, ProductStatus
from app.models.platform_common import PlatformCommon
from app.models.woocommerce import WooCommerceListing
from app.models.woocommerce_order import WooCommerceOrder
from app.models.sync_event import SyncEvent
from app.services.woocommerce.client import WooCommerceClient
from app.services.woocommerce.importer import WooCommerceImporter
from app.services.woocommerce.errors import (
    WCAuthenticationError, WCConnectionError, WCOrderImportError,
    WCInventoryUpdateError, WCAPIError, WCValidationError,
)
from app.services.woocommerce.error_logger import wc_logger
from app.services.woocommerce.error_tracker import WCErrorTracker

logger = logging.getLogger(__name__)


class WooCommerceService:
    """
    High-level service for WooCommerce integration.

    Provides:
    - Import process orchestration
    - Product push (RIFF → WooCommerce)
    - Inventory updates
    - Order import
    """

    def __init__(self, db: AsyncSession, settings: Optional[Settings] = None):
        self.db = db
        self.settings = settings or get_settings()
        self.client = WooCommerceClient()

    # ------------------------------------------------------------------
    # Import process (WooCommerce → RIFF)
    # ------------------------------------------------------------------

    async def run_import_process(self, sync_run_id: uuid.UUID) -> Dict[str, Any]:
        """
        Run the full WooCommerce import process.

        1. Fetches all products from WooCommerce API
        2. Creates/updates Product, PlatformCommon, WooCommerceListing records
        3. Returns statistics

        Args:
            sync_run_id: UUID for tracking this sync run

        Returns:
            Dict with import statistics
        """
        logger.info(f"Starting WooCommerce import process (sync_run_id={sync_run_id})")

        try:
            importer = WooCommerceImporter(self.db)
            stats = await importer.import_all_listings(
                sync_run_id=str(sync_run_id)
            )

            result = {
                "status": "success",
                "sync_run_id": str(sync_run_id),
                "total_from_woocommerce": stats.get("total", 0),
                "created": stats.get("created", 0),
                "updated": stats.get("updated", 0),
                "sku_matched": stats.get("sku_matched", 0),
                "errors": stats.get("errors", 0),
                "skipped": stats.get("skipped", 0),
            }

            # Attach error summary if there were non-fatal errors
            if stats.get("error_summary"):
                result["error_summary"] = stats["error_summary"]

            logger.info(f"WooCommerce import completed: {result}")
            return result

        except (WCAuthenticationError, WCConnectionError) as e:
            # Critical errors -- already logged by importer/client
            logger.error(f"WooCommerce import aborted: {e}")
            return {
                "status": "error",
                "sync_run_id": str(sync_run_id),
                "message": str(e),
                "error_type": type(e).__name__,
                "action_required": (
                    "Check WC API credentials in .env"
                    if isinstance(e, WCAuthenticationError)
                    else "Check WC store URL is reachable"
                ),
            }

        except Exception as e:
            wc_logger.log_error(
                WCAPIError(str(e), operation="run_import_process")
            )
            logger.error(f"WooCommerce import process failed: {e}", exc_info=True)
            return {
                "status": "error",
                "sync_run_id": str(sync_run_id),
                "message": str(e),
                "error_type": type(e).__name__,
            }

    # ------------------------------------------------------------------
    # Product push (RIFF → WooCommerce)
    # ------------------------------------------------------------------

    async def publish_product(self, product_id: int,
                              extra_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Publish a RIFF product to WooCommerce.

        Creates a new WooCommerce product from the local Product record.
        """
        # Check for existing WooCommerce listing to prevent duplicates
        existing_pc = await self.db.execute(
            select(PlatformCommon).where(
                PlatformCommon.product_id == product_id,
                PlatformCommon.platform_name == "woocommerce",
            )
        )
        if existing_pc.scalar_one_or_none():
            raise WCValidationError(
                f"Product {product_id} already has a WooCommerce listing",
                operation="publish_product",
                product_id=product_id,
            )

        # Fetch the local product
        result = await self.db.execute(
            select(Product).where(Product.id == product_id)
        )
        product = result.scalar_one_or_none()
        if not product:
            raise WooCommerceAPIError(f"Product {product_id} not found")

        # Build WooCommerce product payload
        images = []
        if product.primary_image:
            images.append({"src": product.primary_image})
        if product.additional_images:
            for img_url in product.additional_images:
                images.append({"src": img_url})

        wc_payload = {
            "name": product.title or f"{product.brand} {product.model}",
            "type": "simple",
            "regular_price": str(
                calculate_platform_price(
                    "woocommerce",
                    product.base_price or 0,
                    markup_override=self.settings.WC_PRICE_MARKUP_PERCENT,
                )
            ),
            "description": product.description or "",
            "short_description": product.title or "",
            "sku": product.sku,
            "manage_stock": True,
            "stock_quantity": product.quantity if product.quantity is not None else 1,
            "stock_status": "instock" if (product.quantity or 0) > 0 else "outofstock",
            "images": images,
            "meta_data": [
                {"key": "_riff_id", "value": str(product.id)},
                {"key": "_synced_from_riff", "value": "true"},
                {"key": "_riff_last_sync", "value": datetime.now(timezone.utc).isoformat()},
            ],
        }

        # Map RIFF category to WooCommerce category
        if product.category:
            try:
                categories = await self.client.get_categories()
                matched_cat = next(
                    (c for c in categories if c.get("name", "").lower() == product.category.lower()),
                    None,
                )
                if matched_cat:
                    wc_payload["categories"] = [{"id": matched_cat["id"]}]
                else:
                    # Create the category on WooCommerce
                    try:
                        new_cat = await self.client._request(
                            "POST", "products/categories",
                            json={"name": product.category},
                        )
                        wc_payload["categories"] = [{"id": new_cat["id"]}]
                    except Exception as cat_err:
                        logger.warning(
                            f"Could not create WC category '{product.category}': {cat_err}"
                        )
            except Exception as cat_err:
                logger.warning(f"Category mapping failed for product {product_id}: {cat_err}")

        # Merge any extra data, protecting meta_data from being overwritten
        if extra_data:
            extra_meta = extra_data.pop("meta_data", [])
            wc_payload.update(extra_data)
            if extra_meta:
                wc_payload["meta_data"].extend(extra_meta)

        # Create in WooCommerce -- enrich any API error with product context
        try:
            wc_product = await self.client.create_product(wc_payload)
        except WooCommerceAPIError as e:
            if hasattr(e, "product_id"):
                e.product_id = product_id
                e.sku = product.sku
                e.operation = "publish_product"
            raise
        wc_product_id = str(wc_product["id"])

        # Create PlatformCommon + WooCommerceListing locally
        platform_common = PlatformCommon(
            product_id=product.id,
            platform_name="woocommerce",
            external_id=wc_product_id,
            status=ListingStatus.ACTIVE.value,
            sync_status=SyncStatus.SYNCED.value,
            listing_url=wc_product.get("permalink"),
            platform_specific_data={
                "price": wc_product.get("price"),
                "currency": "GBP",
                "stock_quantity": wc_product.get("stock_quantity"),
            },
            last_sync=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        self.db.add(platform_common)
        await self.db.flush()

        wc_listing = WooCommerceListing(
            platform_id=platform_common.id,
            wc_product_id=wc_product_id,
            slug=wc_product.get("slug"),
            permalink=wc_product.get("permalink"),
            title=wc_product.get("name"),
            status=wc_product.get("status"),
            product_type=wc_product.get("type"),
            sku=wc_product.get("sku"),
            price=float(wc_product.get("price") or 0),
            regular_price=float(wc_product.get("regular_price") or 0),
            manage_stock=wc_product.get("manage_stock", True),
            stock_quantity=wc_product.get("stock_quantity"),
            stock_status=wc_product.get("stock_status"),
            extended_attributes=wc_product,
            last_synced_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        self.db.add(wc_listing)
        await self.db.commit()

        logger.info(f"Published product {product_id} to WooCommerce as WC#{wc_product_id}")

        return {
            "success": True,
            "wc_product_id": wc_product_id,
            "permalink": wc_product.get("permalink"),
        }

    # ------------------------------------------------------------------
    # Inventory updates
    # ------------------------------------------------------------------

    async def update_inventory(self, wc_product_id: str, quantity: int) -> bool:
        """Update stock quantity for a WooCommerce product."""
        try:
            stock_status = "instock" if quantity > 0 else "outofstock"
            await self.client.update_product(int(wc_product_id), {
                "stock_quantity": quantity,
                "stock_status": stock_status,
            })

            # Update local record
            result = await self.db.execute(
                select(WooCommerceListing).where(
                    WooCommerceListing.wc_product_id == wc_product_id
                )
            )
            listing = result.scalar_one_or_none()
            if listing:
                listing.stock_quantity = quantity
                listing.stock_status = stock_status
                listing.last_synced_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await self.db.commit()

            logger.info(f"Updated WooCommerce product {wc_product_id} inventory to {quantity}")
            return True

        except WooCommerceAPIError as e:
            inv_error = WCInventoryUpdateError(
                f"Failed to update inventory for WC#{wc_product_id}: {e}",
                operation="update_inventory",
                wc_product_id=wc_product_id,
                http_status=getattr(e, "http_status", None),
            )
            wc_logger.log_error(inv_error)
            logger.error(f"Failed to update WC inventory for {wc_product_id}: {e}")
            raise inv_error from e

    # ------------------------------------------------------------------
    # Product update (RIFF → WooCommerce)
    # ------------------------------------------------------------------

    async def update_product(self, product_id: int, fields: Dict[str, Any]) -> Dict[str, Any]:
        """
        Push updated fields from RIFF to WooCommerce.

        Args:
            product_id: Local RIFF product ID
            fields: Dict of WooCommerce-compatible fields to update

        Returns:
            Updated WC product data
        """
        # Find the WooCommerce listing for this product
        result = await self.db.execute(
            select(PlatformCommon).where(
                PlatformCommon.product_id == product_id,
                PlatformCommon.platform_name == "woocommerce",
            )
        )
        pc = result.scalar_one_or_none()
        if not pc:
            raise WCValidationError(
                f"No WooCommerce listing found for product {product_id}",
                operation="update_product",
                product_id=product_id,
            )

        wc_product_id = int(pc.external_id)

        # Push update to WooCommerce
        wc_data = await self.client.update_product(wc_product_id, fields)

        # Update local WooCommerceListing
        listing_result = await self.db.execute(
            select(WooCommerceListing).where(
                WooCommerceListing.wc_product_id == str(wc_product_id)
            )
        )
        listing = listing_result.scalar_one_or_none()
        if listing:
            for key in ("price", "regular_price", "sale_price", "stock_quantity",
                        "stock_status", "status", "title", "sku"):
                if key in fields:
                    if hasattr(listing, key):
                        setattr(listing, key, wc_data.get(key))
            listing.last_synced_at = datetime.now(timezone.utc).replace(tzinfo=None)
            listing.extended_attributes = wc_data

        # Update PlatformCommon
        pc.last_sync = datetime.now(timezone.utc).replace(tzinfo=None)
        pc.sync_status = SyncStatus.SYNCED.value

        # Create SyncEvent
        sync_event = SyncEvent(
            sync_run_id=uuid.uuid4(),
            platform_name="woocommerce",
            product_id=product_id,
            platform_common_id=pc.id,
            external_id=str(wc_product_id),
            change_type="product_update",
            change_data={"fields_updated": list(fields.keys()), "source": "riff_push"},
            status="processed",
        )
        self.db.add(sync_event)
        await self.db.commit()

        logger.info(f"Updated WC product {wc_product_id} for RIFF product {product_id}")
        return wc_data

    # ------------------------------------------------------------------
    # Product end/deactivate (RIFF → WooCommerce)
    # ------------------------------------------------------------------

    async def end_listing(self, product_id: int, reason: str = "sold") -> bool:
        """
        Deactivate a WooCommerce listing by setting it to draft status.

        Safer than deletion — preserves the product on WooCommerce.

        Args:
            product_id: Local RIFF product ID
            reason: Reason for ending (sold, ended, etc.)

        Returns:
            True if successful
        """
        result = await self.db.execute(
            select(PlatformCommon).where(
                PlatformCommon.product_id == product_id,
                PlatformCommon.platform_name == "woocommerce",
            )
        )
        pc = result.scalar_one_or_none()
        if not pc:
            raise WCValidationError(
                f"No WooCommerce listing found for product {product_id}",
                operation="end_listing",
                product_id=product_id,
            )

        wc_product_id = int(pc.external_id)

        # Set to draft on WooCommerce (safer than delete)
        await self.client.update_product(wc_product_id, {"status": "draft"})

        # Update PlatformCommon
        ended_status = ListingStatus.SOLD.value if reason == "sold" else ListingStatus.ENDED.value
        pc.status = ended_status
        pc.sync_status = SyncStatus.SYNCED.value
        pc.last_sync = datetime.now(timezone.utc).replace(tzinfo=None)

        # Update WooCommerceListing
        listing_result = await self.db.execute(
            select(WooCommerceListing).where(
                WooCommerceListing.wc_product_id == str(wc_product_id)
            )
        )
        listing = listing_result.scalar_one_or_none()
        if listing:
            listing.status = "draft"
            listing.last_synced_at = datetime.now(timezone.utc).replace(tzinfo=None)

        # Create SyncEvent
        sync_event = SyncEvent(
            sync_run_id=uuid.uuid4(),
            platform_name="woocommerce",
            product_id=product_id,
            platform_common_id=pc.id,
            external_id=str(wc_product_id),
            change_type="listing_ended",
            change_data={"reason": reason, "new_status": "draft"},
            status="processed",
        )
        self.db.add(sync_event)
        await self.db.commit()

        logger.info(f"Ended WC listing for product {product_id} (reason: {reason})")
        return True

    # ------------------------------------------------------------------
    # Order import
    # ------------------------------------------------------------------

    async def import_orders(self, status: Optional[str] = None) -> Dict[str, Any]:
        """
        Import orders from WooCommerce into local database.

        Args:
            status: Filter by order status (processing, completed, etc.)

        Returns:
            Statistics dict
        """
        logger.info(f"Importing WooCommerce orders (status={status})")

        orders = await self.client.get_all_orders(status=status)
        created = 0
        updated = 0
        errors = 0
        error_tracker = WCErrorTracker(sync_run_id="orders")

        wc_logger.sync_start("orders", "Order Import")

        for order_data in orders:
            try:
                wc_order_id = str(order_data["id"])

                # Check if already exists
                result = await self.db.execute(
                    select(WooCommerceOrder).where(
                        WooCommerceOrder.wc_order_id == wc_order_id
                    )
                )
                existing = result.scalar_one_or_none()

                billing = order_data.get("billing", {})
                shipping = order_data.get("shipping", {})

                order_fields = {
                    "wc_order_id": wc_order_id,
                    "order_number": str(order_data.get("number", "")),
                    "order_key": order_data.get("order_key"),
                    "status": order_data.get("status"),
                    "payment_method": order_data.get("payment_method"),
                    "payment_method_title": order_data.get("payment_method_title"),
                    "customer_id": str(order_data.get("customer_id", "")),
                    "customer_name": f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip(),
                    "customer_email": billing.get("email"),
                    "shipping_name": f"{shipping.get('first_name', '')} {shipping.get('last_name', '')}".strip(),
                    "shipping_address_1": shipping.get("address_1"),
                    "shipping_address_2": shipping.get("address_2"),
                    "shipping_city": shipping.get("city"),
                    "shipping_state": shipping.get("state"),
                    "shipping_postcode": shipping.get("postcode"),
                    "shipping_country": shipping.get("country"),
                    "total": float(order_data.get("total", 0)),
                    "subtotal": sum(float(li.get("subtotal", 0)) for li in order_data.get("line_items", [])),
                    "shipping_total": float(order_data.get("shipping_total", 0)),
                    "tax_total": float(order_data.get("total_tax", 0)),
                    "discount_total": float(order_data.get("discount_total", 0)),
                    "currency": order_data.get("currency"),
                    "line_items": order_data.get("line_items"),
                    "raw_payload": order_data,
                    "wc_created_at": self._parse_datetime(order_data.get("date_created")),
                    "wc_modified_at": self._parse_datetime(order_data.get("date_modified")),
                }

                if existing:
                    old_status = existing.status
                    for key, value in order_fields.items():
                        setattr(existing, key, value)
                    # Link to RIFF product if not already linked
                    if not existing.product_id:
                        await self._link_order_to_product(existing, order_data)
                    # Process sale or handle cancellation/refund
                    await self._process_order_sale(existing, old_status)
                    updated += 1
                else:
                    new_order = WooCommerceOrder(**order_fields)
                    self.db.add(new_order)
                    await self.db.flush()
                    # Link the new order to a RIFF product
                    await self._link_order_to_product(new_order, order_data)
                    # Process sale for new orders
                    await self._process_order_sale(new_order)
                    created += 1

            except Exception as e:
                order_error = WCOrderImportError(
                    f"Failed to process order {order_data.get('id')}: {e}",
                    operation="import_order",
                    wc_product_id=str(order_data.get("id", "")),
                )
                error_tracker.record(order_error)
                wc_logger.log_error(order_error)
                logger.error(f"Error processing WC order {order_data.get('id')}: {e}")
                errors += 1

        await self.db.commit()

        result = {
            "total": len(orders),
            "created": created,
            "updated": updated,
            "errors": errors,
        }

        error_summary = (
            error_tracker.get_summary()
            if error_tracker.error_count > 0
            else None
        )
        if error_summary:
            result["error_summary"] = error_summary

        wc_logger.sync_complete(
            "orders", result, error_summary=error_summary
        )
        logger.info(f"WooCommerce order import completed: {result}")
        return result

    # ------------------------------------------------------------------
    # Product retrieval
    # ------------------------------------------------------------------

    async def get_product(self, wc_product_id: str) -> Dict[str, Any]:
        """Get product details from WooCommerce."""
        return await self.client.get_product(int(wc_product_id))

    # ------------------------------------------------------------------
    # Cross-platform inventory propagation
    # ------------------------------------------------------------------

    # WooCommerce order statuses that indicate a confirmed sale
    _SALE_STATUSES = {"processing", "completed"}
    _CANCELLED_STATUSES = {"cancelled", "refunded", "failed"}

    async def _process_order_sale(
        self, order: WooCommerceOrder, old_status: Optional[str] = None
    ) -> None:
        """
        Process inventory changes for a WooCommerce order sale.

        - If order is processing/completed and not yet processed: decrement stock
        - If order was processed but now cancelled/refunded: restore stock
        """
        current_status = order.status

        # Case 1: New sale — decrement inventory
        if current_status in self._SALE_STATUSES and not order.sale_processed:
            if not order.product_id:
                return

            result = await self.db.execute(
                select(Product).where(Product.id == order.product_id)
            )
            product = result.scalar_one_or_none()
            if not product:
                return

            # Determine quantity from line items
            qty_sold = 1
            if order.line_items:
                for item in order.line_items:
                    if str(item.get("product_id", "")) == str(
                        getattr(order, "_matched_wc_product_id", "")
                    ) or item.get("sku") == product.sku:
                        qty_sold = item.get("quantity", 1)
                        break

            product.quantity = max(0, (product.quantity or 0) - qty_sold)
            if product.quantity == 0:
                product.status = ProductStatus.SOLD.value

            order.sale_processed = True
            self.db.add(product)

            # Create SyncEvent for the sale
            sync_event = SyncEvent(
                sync_run_id=uuid.uuid4(),
                platform_name="woocommerce",
                product_id=product.id,
                platform_common_id=order.platform_listing_id,
                external_id=order.wc_order_id,
                change_type="order_sale",
                change_data={
                    "order_id": order.wc_order_id,
                    "quantity_sold": qty_sold,
                    "new_quantity": product.quantity,
                    "order_status": current_status,
                },
                status="pending",
            )
            self.db.add(sync_event)

            logger.info(
                f"WC order {order.wc_order_id}: decremented product {product.id} "
                f"by {qty_sold} (new qty: {product.quantity})"
            )

        # Case 2: Cancellation/refund — restore inventory
        elif (
            current_status in self._CANCELLED_STATUSES
            and order.sale_processed
            and old_status in self._SALE_STATUSES
        ):
            if not order.product_id:
                return

            result = await self.db.execute(
                select(Product).where(Product.id == order.product_id)
            )
            product = result.scalar_one_or_none()
            if not product:
                return

            # Restore quantity
            qty_to_restore = 1
            if order.line_items:
                for item in order.line_items:
                    if item.get("sku") == product.sku:
                        qty_to_restore = item.get("quantity", 1)
                        break

            product.quantity = (product.quantity or 0) + qty_to_restore
            if product.status == ProductStatus.SOLD.value:
                product.status = ProductStatus.ACTIVE.value

            order.sale_processed = False
            self.db.add(product)

            # Create SyncEvent for cancellation
            sync_event = SyncEvent(
                sync_run_id=uuid.uuid4(),
                platform_name="woocommerce",
                product_id=product.id,
                platform_common_id=order.platform_listing_id,
                external_id=order.wc_order_id,
                change_type="order_cancelled",
                change_data={
                    "order_id": order.wc_order_id,
                    "quantity_restored": qty_to_restore,
                    "new_quantity": product.quantity,
                    "old_status": old_status,
                    "new_status": current_status,
                },
                status="pending",
            )
            self.db.add(sync_event)

            logger.info(
                f"WC order {order.wc_order_id} cancelled/refunded: restored "
                f"{qty_to_restore} to product {product.id} (new qty: {product.quantity})"
            )

    # ------------------------------------------------------------------
    # Order-product linking
    # ------------------------------------------------------------------

    async def _link_order_to_product(
        self, order: WooCommerceOrder, order_data: Dict[str, Any]
    ) -> None:
        """
        Attempt to link an order to a RIFF product via line items.

        Matching strategy (in priority order):
        1. SKU field against Product.sku
        2. WC product_id against WooCommerceListing.wc_product_id
        3. _riff_id meta in line item meta_data

        Links to the first matched product. Logs a warning for multi-item orders.
        """
        line_items = order_data.get("line_items", [])
        if not line_items:
            return

        if len(line_items) > 1:
            logger.warning(
                f"WC order {order.wc_order_id} has {len(line_items)} line items — "
                f"will link to first matched product only"
            )

        for item in line_items:
            product = None
            platform_common = None

            # Strategy 1: Match by SKU
            item_sku = item.get("sku")
            if item_sku:
                result = await self.db.execute(
                    select(Product).where(Product.sku == item_sku)
                )
                product = result.scalar_one_or_none()

            # Strategy 2: Match by WC product_id → WooCommerceListing
            if not product:
                wc_pid = str(item.get("product_id", ""))
                if wc_pid:
                    result = await self.db.execute(
                        select(WooCommerceListing).where(
                            WooCommerceListing.wc_product_id == wc_pid
                        )
                    )
                    wc_listing = result.scalar_one_or_none()
                    if wc_listing and wc_listing.platform_id:
                        pc_result = await self.db.execute(
                            select(PlatformCommon).where(
                                PlatformCommon.id == wc_listing.platform_id
                            )
                        )
                        platform_common = pc_result.scalar_one_or_none()
                        if platform_common and platform_common.product_id:
                            p_result = await self.db.execute(
                                select(Product).where(
                                    Product.id == platform_common.product_id
                                )
                            )
                            product = p_result.scalar_one_or_none()

            # Strategy 3: Match by _riff_id meta
            if not product:
                for meta in item.get("meta_data", []):
                    if meta.get("key") == "_riff_id":
                        riff_id = meta.get("value")
                        if riff_id:
                            try:
                                result = await self.db.execute(
                                    select(Product).where(Product.id == int(riff_id))
                                )
                                product = result.scalar_one_or_none()
                            except (ValueError, TypeError):
                                pass
                        break

            if product:
                order.product_id = product.id
                # Find PlatformCommon if not already found
                if not platform_common:
                    pc_result = await self.db.execute(
                        select(PlatformCommon).where(
                            PlatformCommon.product_id == product.id,
                            PlatformCommon.platform_name == "woocommerce",
                        )
                    )
                    platform_common = pc_result.scalar_one_or_none()
                if platform_common:
                    order.platform_listing_id = platform_common.id
                logger.info(
                    f"Linked WC order {order.wc_order_id} to product {product.id} "
                    f"(SKU: {product.sku})"
                )
                return  # Link to first match only

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_datetime(self, dt_str: Optional[str]) -> Optional[datetime]:
        """Parse WooCommerce datetime to naive UTC."""
        if not dt_str:
            return None
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            if dt.tzinfo:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except (ValueError, TypeError):
            return None
