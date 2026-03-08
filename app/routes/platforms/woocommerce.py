# app/routes/platforms/woocommerce.py
"""
API routes for WooCommerce platform integration.

Provides endpoints for:
- Syncing inventory from WooCommerce
- Publishing products to WooCommerce
- Updating inventory levels
- Importing orders
- Testing connectivity
"""

import hashlib
import hmac
import base64
import json
import logging
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request, Header
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.woocommerce_service import WooCommerceService
from app.services.websockets.manager import manager
from app.services.activity_logger import ActivityLogger
from app.database import async_session
from app.dependencies import get_db
from app.core.config import Settings, get_settings
from app.core.exceptions import WooCommerceAPIError
from app.models.platform_common import PlatformCommon, ListingStatus
from app.services.woocommerce.errors import (
    WCAuthenticationError, WCConnectionError, WCProductNotFoundError,
    WCValidationError, WCInventoryUpdateError,
)

router = APIRouter(prefix="/api", tags=["woocommerce"])

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Sync endpoint (WooCommerce → RIFF)
# ------------------------------------------------------------------

@router.post("/sync/woocommerce")
async def sync_woocommerce(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Run WooCommerce read sync - download latest inventory and update local database."""
    sync_run_id = uuid.uuid4()
    logger.info(f"Initiating WooCommerce sync with run_id: {sync_run_id}")

    background_tasks.add_task(
        run_woocommerce_sync_background,
        settings,
        sync_run_id,
    )

    return {
        "status": "success",
        "message": "WooCommerce sync started",
        "sync_run_id": str(sync_run_id),
    }


async def run_woocommerce_sync_background(
    settings: Settings,
    sync_run_id: uuid.UUID,
    db: AsyncSession = None,
):
    """Run WooCommerce sync in background with WebSocket updates.

    Args:
        settings: Application settings.
        sync_run_id: UUID for this sync run.
        db: Optional database session. If provided, uses it directly
            (called from sync_all). If None, creates its own session
            (called from the standalone sync endpoint).
    """
    logger.info(f"Starting WooCommerce sync background task for run_id: {sync_run_id}")

    if db is not None:
        await _run_woocommerce_sync_with_session(db, settings, sync_run_id)
        return

    async with async_session() as db:
        await _run_woocommerce_sync_with_session(db, settings, sync_run_id)


async def _run_woocommerce_sync_with_session(
    db: AsyncSession,
    settings: Settings,
    sync_run_id: uuid.UUID,
):
    """Core sync logic shared by both standalone and sync_all code paths."""
    activity_logger = ActivityLogger(db)

    try:
        # Send start notification
        await manager.broadcast({
            "type": "sync_started",
            "platform": "woocommerce",
            "sync_run_id": str(sync_run_id),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # Run import
        wc_service = WooCommerceService(db, settings)
        result = await wc_service.run_import_process(sync_run_id)

        if result.get("status") == "success" or "total_from_woocommerce" in result:
            # Update last_sync timestamp for WooCommerce platform entries
            update_query = text("""
                UPDATE platform_common
                SET last_sync = :now,
                    sync_status = 'SYNCED'
                WHERE platform_name = 'woocommerce'
            """).bindparams(now=datetime.now(timezone.utc))
            await db.execute(update_query)

            # Log successful sync
            await activity_logger.log_activity(
                action="sync",
                entity_type="platform",
                entity_id="woocommerce",
                platform="woocommerce",
                details={
                    "status": "success",
                    "total": result.get("total_from_woocommerce", 0),
                    "created": result.get("created", 0),
                    "updated": result.get("updated", 0),
                    "errors": result.get("errors", 0),
                    "icon": "✅",
                    "message": f"Synced WooCommerce ({result.get('total_from_woocommerce', 0)} items)",
                },
            )

            # Send success notification (include error summary if present)
            broadcast_data = {
                "type": "sync_completed",
                "platform": "woocommerce",
                "status": "success",
                "data": result,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if result.get("error_summary"):
                broadcast_data["error_summary"] = result["error_summary"]
            await manager.broadcast(broadcast_data)

            logger.info(f"WooCommerce import result: {result}")

        else:
            # Log failed sync
            await activity_logger.log_activity(
                action="sync_error",
                entity_type="platform",
                entity_id="woocommerce",
                platform="woocommerce",
                details={
                    "error": result.get("message", "Unknown error"),
                    "sync_run_id": str(sync_run_id),
                },
            )

            await manager.broadcast({
                "type": "sync_completed",
                "platform": "woocommerce",
                "status": "error",
                "message": result.get("message", "Unknown error"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            logger.error(f"WooCommerce sync error: {result.get('message')}")

        await db.commit()

    except Exception as e:
        await db.rollback()
        error_message = str(e)
        logger.exception(f"WooCommerce sync background task failed: {error_message}")

        await activity_logger.log_activity(
            action="sync_error",
            entity_type="platform",
            entity_id="woocommerce",
            platform="woocommerce",
            details={
                "error": error_message,
                "sync_run_id": str(sync_run_id),
            },
        )
        await db.commit()

        await manager.broadcast({
            "type": "sync_completed",
            "platform": "woocommerce",
            "status": "error",
            "message": error_message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })


# ------------------------------------------------------------------
# Publish / push product (RIFF → WooCommerce)
# ------------------------------------------------------------------

@router.post("/products/{product_id}/publish/woocommerce")
async def publish_to_woocommerce(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Publish a RIFF product to WooCommerce.

    Creates a new product on the WooCommerce store.
    """
    try:
        service = WooCommerceService(db, settings)
        result = await service.publish_product(product_id)
        return result
    except WCAuthenticationError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except WCConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except WCValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except WCProductNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except WooCommerceAPIError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error publishing to WooCommerce: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Product update (RIFF → WooCommerce)
# ------------------------------------------------------------------

@router.put("/products/{product_id}/woocommerce")
async def update_woocommerce_product(
    product_id: int,
    fields: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Update a WooCommerce product with the given fields."""
    try:
        service = WooCommerceService(db, settings)
        result = await service.update_product(product_id, fields)
        return {"success": True, "data": result}
    except WCValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except WCProductNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except WooCommerceAPIError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating WooCommerce product: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Product end/deactivate
# ------------------------------------------------------------------

@router.post("/products/{product_id}/woocommerce/end")
async def end_woocommerce_listing(
    product_id: int,
    reason: str = "sold",
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """End/deactivate a WooCommerce listing (sets to draft, does not delete)."""
    try:
        service = WooCommerceService(db, settings)
        success = await service.end_listing(product_id, reason=reason)
        return {"success": success}
    except WCValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except WCProductNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except WooCommerceAPIError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error ending WooCommerce listing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Inventory update
# ------------------------------------------------------------------

@router.put("/woocommerce/products/{wc_product_id}/inventory")
async def update_woocommerce_inventory(
    wc_product_id: str,
    quantity: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Update inventory for a WooCommerce product."""
    if quantity < 0:
        raise HTTPException(status_code=400, detail="Quantity cannot be negative")

    try:
        service = WooCommerceService(db, settings)
        success = await service.update_inventory(wc_product_id, quantity)
        return {"success": success}
    except WCAuthenticationError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except WCProductNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except WCInventoryUpdateError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except WooCommerceAPIError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Get product from WooCommerce
# ------------------------------------------------------------------

@router.get("/woocommerce/products/{wc_product_id}")
async def get_woocommerce_product(
    wc_product_id: str,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Get product details from WooCommerce."""
    try:
        service = WooCommerceService(db, settings)
        product = await service.get_product(wc_product_id)
        return product
    except WCAuthenticationError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except WCProductNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except WooCommerceAPIError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Order import
# ------------------------------------------------------------------

@router.post("/sync/woocommerce/orders")
async def sync_woocommerce_orders(
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Import orders from WooCommerce."""
    try:
        service = WooCommerceService(db, settings)
        result = await service.import_orders(status=status)
        return {"status": "success", **result}
    except WCAuthenticationError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except WCConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except WooCommerceAPIError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error importing WooCommerce orders: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Connectivity test
# ------------------------------------------------------------------

@router.get("/woocommerce/test-connection")
async def test_woocommerce_connection(
    settings: Settings = Depends(get_settings),
):
    """Test WooCommerce API connectivity."""
    try:
        from app.services.woocommerce.client import WooCommerceClient
        async with WooCommerceClient() as client:
            connected = await client.test_connection()
            if connected:
                return {"status": "connected", "store_url": settings.WC_STORE_URL}
            else:
                return {"status": "failed", "message": "Could not connect to WooCommerce API"}
    except Exception as e:
        # NOTE: test-connection intentionally returns a dict with status/error rather than
        # raising HTTPException, as this is a diagnostic endpoint — the "error" IS the response.
        return {"status": "error", "message": str(e)}


# ==================================================================
# Webhook endpoints (WooCommerce → RIFF, no auth — signature verified)
# ==================================================================

webhook_router = APIRouter(tags=["woocommerce-webhooks"])


# -- Delivery ID deduplication (in-memory, TTL-based) ---------------

class _DeliveryIdCache:
    """In-memory cache for WooCommerce webhook delivery ID deduplication.

    WC-P3-072: Namespaced by store identifier so different WooCommerce
    stores do not collide with each other's delivery IDs.

    Limitations:
    - Cache is lost on application restart — webhooks received before restart
      may be re-processed after restart.
    - Cache is per-process — in multi-worker deployments (multiple Uvicorn
      workers), duplicate webhooks landing on different workers are not
      deduplicated.
    - For multi-worker deployments, consider migrating to Redis-based
      deduplication.

    Current capacity: 1,000 delivery IDs per store with TTL-based eviction (24h).
    """

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 86400):
        self._caches: Dict[str, OrderedDict] = {}
        self._max_size = max_size
        self._ttl = ttl_seconds

    def seen(self, delivery_id: str, store_id: str = "global") -> bool:
        """Return True if this delivery ID has already been processed for this store."""
        if store_id not in self._caches:
            self._caches[store_id] = OrderedDict()
        cache = self._caches[store_id]
        self._evict_expired(cache)
        if delivery_id in cache:
            return True
        cache[delivery_id] = time.time()
        if len(cache) > self._max_size:
            cache.popitem(last=False)
        return False

    def _evict_expired(self, cache: OrderedDict):
        cutoff = time.time() - self._ttl
        while cache:
            oldest_key = next(iter(cache))
            if cache[oldest_key] < cutoff:
                cache.pop(oldest_key)
            else:
                break


_delivery_cache = _DeliveryIdCache()


# -- Signature verification ----------------------------------------

def verify_wc_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    Verify a WooCommerce webhook signature (HMAC-SHA256, base64-encoded).

    Args:
        payload: Raw request body bytes
        signature: Value of X-WC-Webhook-Signature header
        secret: WC_WEBHOOK_SECRET from configuration

    Returns:
        True if the signature is valid
    """
    if not signature or not secret:
        return False
    expected = base64.b64encode(
        hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    ).decode("utf-8")
    return hmac.compare_digest(expected, signature)


# -- Payload validation helpers ------------------------------------

def _validate_webhook_product_payload(payload: dict) -> dict:
    """Validate and sanitise a WooCommerce product webhook payload."""
    validated = {}

    # ID must be a positive integer
    product_id = payload.get("id")
    if not isinstance(product_id, int) or product_id <= 0:
        raise ValueError(f"Invalid product id: {product_id}")
    validated["id"] = product_id

    # stock_quantity: non-negative integer or None
    stock_qty = payload.get("stock_quantity")
    if stock_qty is not None:
        if not isinstance(stock_qty, (int, float)) or stock_qty < 0:
            stock_qty = 0
        validated["stock_quantity"] = int(stock_qty)

    # price fields: parseable positive number or empty
    for price_field in ("regular_price", "sale_price", "price"):
        price_val = payload.get(price_field, "")
        if price_val and price_val not in ("", None):
            try:
                parsed = float(price_val)
                if parsed < 0:
                    price_val = "0"
            except (ValueError, TypeError):
                price_val = "0"
        validated[price_field] = price_val

    # images: limit to 50
    images = payload.get("images", [])
    if isinstance(images, list):
        validated["images"] = images[:50]

    # description: truncate to 500KB
    for desc_field in ("description", "short_description"):
        desc = payload.get(desc_field, "")
        if isinstance(desc, str) and len(desc) > 500_000:
            desc = desc[:500_000]
        validated[desc_field] = desc

    # Pass through remaining safe fields
    safe_fields = ("name", "sku", "slug", "status", "type", "manage_stock",
                   "stock_status", "categories", "tags", "meta_data")
    for field in safe_fields:
        if field in payload:
            validated[field] = payload[field]

    return validated


def _validate_webhook_order_payload(payload: dict) -> dict:
    """Validate and sanitise a WooCommerce order webhook payload."""
    validated = {}

    # ID must be a positive integer
    order_id = payload.get("id")
    if not isinstance(order_id, int) or order_id <= 0:
        raise ValueError(f"Invalid order id: {order_id}")
    validated["id"] = order_id

    # Safe pass-through fields
    safe_fields = (
        "number", "order_key", "status", "payment_method",
        "payment_method_title", "customer_id", "billing", "shipping",
        "total", "shipping_total", "total_tax", "discount_total",
        "currency", "line_items", "date_created", "date_modified",
    )
    for field in safe_fields:
        if field in payload:
            validated[field] = payload[field]

    return validated


# -- Ping detection helper (WC-P3-015) --------------------------------

def _is_webhook_ping(payload: dict) -> bool:
    """Detect WooCommerce webhook ping payloads.

    WooCommerce sends an empty/minimal payload when a webhook is first
    created to verify the delivery URL is reachable.  These payloads
    lack a real ``id`` field and should be acknowledged with 200 rather
    than rejected by validation.
    """
    if not payload:
        return True
    # Ping payloads typically have webhook_id but no product/order id
    if payload.get("webhook_id") and not payload.get("id"):
        return True
    return False


# -- Product webhook -----------------------------------------------

@webhook_router.post("/webhooks/woocommerce/product")
async def handle_wc_product_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    """
    Handle WooCommerce product webhooks.

    Topics: product.created, product.updated, product.deleted, product.restored
    """
    body = await request.body()

    # Extract headers
    signature = request.headers.get("X-WC-Webhook-Signature", "")
    topic = request.headers.get("X-WC-Webhook-Topic", "")
    delivery_id = request.headers.get("X-WC-Webhook-Delivery-ID", "")
    source = request.headers.get("X-WC-Webhook-Source", "")

    # Verify signature
    if not verify_wc_webhook_signature(body, signature, settings.WC_WEBHOOK_SECRET):
        logger.warning(f"Invalid WC product webhook signature from {source}")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Deduplicate
    if delivery_id and _delivery_cache.seen(delivery_id):
        logger.info(f"Duplicate WC webhook delivery {delivery_id} — skipping")
        return {"status": "duplicate"}

    # Parse payload
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    logger.info(f"WC product webhook: topic={topic}, product_id={payload.get('id')}")

    # WC-P3-015: Detect and acknowledge ping payloads before validation
    if _is_webhook_ping(payload):
        logger.info("WC product webhook ping received — acknowledging")
        return {"status": "pong"}

    # Validate payload before passing to background task
    try:
        validated_payload = _validate_webhook_product_payload(payload)
    except ValueError as e:
        logger.warning(f"Invalid WC product webhook payload: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    # WC-P3-016: Validate webhook source header against configured store URL
    source = request.headers.get("X-WC-Webhook-Source", "")
    if source:
        expected_source = (settings.WC_STORE_URL or "").rstrip("/")
        actual_source = source.rstrip("/")
        if expected_source and actual_source != expected_source:
            logger.warning(
                f"Webhook source mismatch: expected {expected_source}, got {actual_source}"
            )

    # Process in background
    background_tasks.add_task(
        _process_product_webhook_background,
        topic,
        validated_payload,
        settings,
    )

    return {"status": "accepted"}


async def _process_product_webhook_background(
    topic: str,
    payload: Dict[str, Any],
    settings: Settings,
    wc_store=None,
):
    """Process a WooCommerce product webhook in the background."""
    async with async_session() as db:
        try:
            service = WooCommerceService(db, settings, wc_store=wc_store)
            wc_product_id = str(payload.get("id", ""))

            # WC-P3-018: Check for missing required fields and re-fetch if needed
            required_fields = ["id", "name", "sku", "status", "type"]
            missing = [f for f in required_fields if f not in payload]
            if missing and payload.get("id"):
                logger.warning(
                    f"Webhook payload missing fields: {missing}. Re-fetching from API."
                )
                try:
                    payload = await service.client.get_product(int(wc_product_id))
                except Exception as fetch_err:
                    logger.error(
                        f"Failed to re-fetch WC product {wc_product_id}: {fetch_err}"
                    )

            if topic == "product.created":
                from app.services.woocommerce.importer import WooCommerceImporter
                importer = WooCommerceImporter(db, wc_store=wc_store)
                await importer._process_single_product(payload)
                await db.commit()
                logger.info(f"Webhook: imported new WC product {wc_product_id}")

            elif topic == "product.updated":
                from app.services.woocommerce.importer import WooCommerceImporter
                importer = WooCommerceImporter(db, wc_store=wc_store)
                await importer._process_single_product(payload)
                await db.commit()
                logger.info(f"Webhook: updated WC product {wc_product_id}")

            elif topic == "product.deleted":
                from app.models.woocommerce import WooCommerceListing
                from app.models.sync_event import SyncEvent
                from sqlalchemy import select

                result = await db.execute(
                    select(WooCommerceListing).where(
                        WooCommerceListing.wc_product_id == wc_product_id
                    )
                )
                listing = result.scalar_one_or_none()
                if listing:
                    listing.status = "trash"
                    if listing.platform_id:
                        pc_result = await db.execute(
                            select(PlatformCommon).where(
                                PlatformCommon.id == listing.platform_id
                            )
                        )
                        pc = pc_result.scalar_one_or_none()
                        if pc:
                            pc.status = ListingStatus.DELETED.value
                            event = SyncEvent(
                                sync_run_id=uuid.uuid4(),
                                platform_name="woocommerce",
                                product_id=pc.product_id,
                                platform_common_id=pc.id,
                                external_id=wc_product_id,
                                change_type="listing_deleted",
                                change_data={"source": "webhook", "topic": topic},
                                status="pending",
                            )
                            db.add(event)
                    await db.commit()
                    logger.info(f"Webhook: marked WC product {wc_product_id} as deleted")

            elif topic == "product.restored":
                from app.models.woocommerce import WooCommerceListing
                from app.models.sync_event import SyncEvent
                from sqlalchemy import select

                result = await db.execute(
                    select(WooCommerceListing).where(
                        WooCommerceListing.wc_product_id == wc_product_id
                    )
                )
                listing = result.scalar_one_or_none()
                if listing:
                    listing.status = "draft"
                    if listing.platform_id:
                        pc_result = await db.execute(
                            select(PlatformCommon).where(
                                PlatformCommon.id == listing.platform_id
                            )
                        )
                        pc = pc_result.scalar_one_or_none()
                        if pc:
                            pc.status = ListingStatus.DRAFT.value
                            event = SyncEvent(
                                sync_run_id=uuid.uuid4(),
                                platform_name="woocommerce",
                                product_id=pc.product_id,
                                platform_common_id=pc.id,
                                external_id=wc_product_id,
                                change_type="listing_restored",
                                change_data={"source": "webhook", "topic": topic},
                                status="pending",
                            )
                            db.add(event)
                    await db.commit()
                    logger.info(f"Webhook: restored WC product {wc_product_id}")

        except Exception as e:
            await db.rollback()
            logger.error(f"Error processing WC product webhook ({topic}): {e}", exc_info=True)


# -- Order webhook -------------------------------------------------

@webhook_router.post("/webhooks/woocommerce/order")
async def handle_wc_order_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    """
    Handle WooCommerce order webhooks.

    Topics: order.created, order.updated
    """
    body = await request.body()

    signature = request.headers.get("X-WC-Webhook-Signature", "")
    topic = request.headers.get("X-WC-Webhook-Topic", "")
    delivery_id = request.headers.get("X-WC-Webhook-Delivery-ID", "")
    source = request.headers.get("X-WC-Webhook-Source", "")

    if not verify_wc_webhook_signature(body, signature, settings.WC_WEBHOOK_SECRET):
        logger.warning(f"Invalid WC order webhook signature from {source}")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    if delivery_id and _delivery_cache.seen(delivery_id):
        logger.info(f"Duplicate WC webhook delivery {delivery_id} — skipping")
        return {"status": "duplicate"}

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    logger.info(f"WC order webhook: topic={topic}, order_id={payload.get('id')}")

    # WC-P3-015: Detect and acknowledge ping payloads before validation
    if _is_webhook_ping(payload):
        logger.info("WC order webhook ping received — acknowledging")
        return {"status": "pong"}

    # Validate payload before passing to background task
    try:
        validated_payload = _validate_webhook_order_payload(payload)
    except ValueError as e:
        logger.warning(f"Invalid WC order webhook payload: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    # WC-P3-016: Validate webhook source header
    source = request.headers.get("X-WC-Webhook-Source", "")
    if source:
        expected_source = (settings.WC_STORE_URL or "").rstrip("/")
        actual_source = source.rstrip("/")
        if expected_source and actual_source != expected_source:
            logger.warning(
                f"Webhook source mismatch: expected {expected_source}, got {actual_source}"
            )

    background_tasks.add_task(
        _process_order_webhook_background,
        topic,
        validated_payload,
        settings,
    )

    return {"status": "accepted"}


async def _process_order_webhook_background(
    topic: str,
    payload: Dict[str, Any],
    settings: Settings,
    wc_store=None,
):
    """Process a WooCommerce order webhook in the background."""
    async with async_session() as db:
        try:
            service = WooCommerceService(db, settings, wc_store=wc_store)

            if topic in ("order.created", "order.updated"):
                # Process the single order from the webhook payload directly
                await service.import_single_order(payload)
                logger.info(f"Webhook: processed WC order {payload.get('id')} ({topic})")

        except Exception as e:
            await db.rollback()
            logger.error(f"Error processing WC order webhook ({topic}): {e}", exc_info=True)


# ==================================================================
# Per-tenant webhook endpoints (WC-P3-069)
# ==================================================================

@webhook_router.post("/webhooks/woocommerce/{store_id}/product")
async def handle_wc_product_webhook_tenant(
    store_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    """Handle WooCommerce product webhooks for a specific store."""
    from sqlalchemy import select as sa_select
    from app.models.woocommerce_store import WooCommerceStore

    body = await request.body()

    signature = request.headers.get("X-WC-Webhook-Signature", "")
    topic = request.headers.get("X-WC-Webhook-Topic", "")
    delivery_id = request.headers.get("X-WC-Webhook-Delivery-ID", "")

    # Load store
    async with async_session() as db:
        result = await db.execute(
            sa_select(WooCommerceStore).where(
                WooCommerceStore.id == store_id,
                WooCommerceStore.is_active == True,
            )
        )
        wc_store = result.scalar_one_or_none()

    if not wc_store:
        raise HTTPException(status_code=404, detail="WooCommerce store not found")

    # Verify signature with per-store secret
    if not verify_wc_webhook_signature(body, signature, wc_store.webhook_secret or ""):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Deduplicate per-store
    cache_key = str(store_id)
    if delivery_id and _delivery_cache.seen(delivery_id, store_id=cache_key):
        return {"status": "duplicate"}

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if _is_webhook_ping(payload):
        logger.info(f"WC product webhook ping for store {store_id}")
        return {"status": "pong"}

    try:
        validated_payload = _validate_webhook_product_payload(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # WC-P3-016: Validate webhook source against store URL
    source = request.headers.get("X-WC-Webhook-Source", "")
    if wc_store and source:
        expected_source = wc_store.store_url.rstrip("/")
        actual_source = source.rstrip("/")
        if expected_source and actual_source != expected_source:
            logger.warning(
                f"Webhook source mismatch for store {store_id}: "
                f"expected {expected_source}, got {actual_source}"
            )

    background_tasks.add_task(
        _process_product_webhook_background, topic, validated_payload, settings, wc_store,
    )
    return {"status": "accepted"}


@webhook_router.post("/webhooks/woocommerce/{store_id}/order")
async def handle_wc_order_webhook_tenant(
    store_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    """Handle WooCommerce order webhooks for a specific store."""
    from sqlalchemy import select as sa_select
    from app.models.woocommerce_store import WooCommerceStore

    body = await request.body()

    signature = request.headers.get("X-WC-Webhook-Signature", "")
    topic = request.headers.get("X-WC-Webhook-Topic", "")
    delivery_id = request.headers.get("X-WC-Webhook-Delivery-ID", "")

    # Load store
    async with async_session() as db:
        result = await db.execute(
            sa_select(WooCommerceStore).where(
                WooCommerceStore.id == store_id,
                WooCommerceStore.is_active == True,
            )
        )
        wc_store = result.scalar_one_or_none()

    if not wc_store:
        raise HTTPException(status_code=404, detail="WooCommerce store not found")

    if not verify_wc_webhook_signature(body, signature, wc_store.webhook_secret or ""):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    cache_key = str(store_id)
    if delivery_id and _delivery_cache.seen(delivery_id, store_id=cache_key):
        return {"status": "duplicate"}

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if _is_webhook_ping(payload):
        logger.info(f"WC order webhook ping for store {store_id}")
        return {"status": "pong"}

    try:
        validated_payload = _validate_webhook_order_payload(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # WC-P3-016: Validate webhook source against store URL
    source = request.headers.get("X-WC-Webhook-Source", "")
    if wc_store and source:
        expected_source = wc_store.store_url.rstrip("/")
        actual_source = source.rstrip("/")
        if expected_source and actual_source != expected_source:
            logger.warning(
                f"Webhook source mismatch for store {store_id}: "
                f"expected {expected_source}, got {actual_source}"
            )

    background_tasks.add_task(
        _process_order_webhook_background, topic, validated_payload, settings, wc_store,
    )
    return {"status": "accepted"}


# ==================================================================
# WooCommerce Store CRUD endpoints (WC-P3-066)
# ==================================================================

store_router = APIRouter(prefix="/api/woocommerce/stores", tags=["woocommerce-stores"])


@store_router.post("")
async def create_wc_store(
    name: str,
    store_url: str,
    consumer_key: str,
    consumer_secret: str,
    webhook_secret: str = "",
    price_markup_percent: float = 0.0,
    db: AsyncSession = Depends(get_db),
):
    """Connect a new WooCommerce store."""
    from app.models.woocommerce_store import WooCommerceStore

    # Validate credentials by testing connection
    try:
        client = WooCommerceClient(
            store_url=store_url,
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
        )
        connected = await client.test_connection()
        await client.close()
        if not connected:
            raise HTTPException(status_code=400, detail="Could not connect to WooCommerce API")
    except WCAuthenticationError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Connection test failed: {e}")

    store = WooCommerceStore(
        name=name,
        store_url=store_url.rstrip("/"),
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        webhook_secret=webhook_secret,
        price_markup_percent=price_markup_percent,
    )
    db.add(store)
    await db.commit()
    await db.refresh(store)

    return {
        "id": store.id,
        "name": store.name,
        "store_url": store.store_url,
        "is_active": store.is_active,
        "price_markup_percent": store.price_markup_percent,
    }


@store_router.get("")
async def list_wc_stores(db: AsyncSession = Depends(get_db)):
    """List all connected WooCommerce stores."""
    from sqlalchemy import select as sa_select
    from app.models.woocommerce_store import WooCommerceStore

    result = await db.execute(sa_select(WooCommerceStore).order_by(WooCommerceStore.id))
    stores = result.scalars().all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "store_url": s.store_url,
            "is_active": s.is_active,
            "sync_status": s.sync_status,
            "last_sync_at": s.last_sync_at.isoformat() if s.last_sync_at else None,
            "price_markup_percent": s.price_markup_percent,
        }
        for s in stores
    ]


@store_router.get("/{store_id}")
async def get_wc_store(store_id: int, db: AsyncSession = Depends(get_db)):
    """Get a WooCommerce store by ID."""
    from app.models.woocommerce_store import WooCommerceStore

    store = await db.get(WooCommerceStore, store_id)
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    return {
        "id": store.id,
        "name": store.name,
        "store_url": store.store_url,
        "is_active": store.is_active,
        "sync_status": store.sync_status,
        "last_sync_at": store.last_sync_at.isoformat() if store.last_sync_at else None,
        "price_markup_percent": store.price_markup_percent,
        "webhook_url_product": f"/webhooks/woocommerce/{store.id}/product",
        "webhook_url_order": f"/webhooks/woocommerce/{store.id}/order",
    }


@store_router.put("/{store_id}")
async def update_wc_store(
    store_id: int,
    fields: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
):
    """Update a WooCommerce store's settings."""
    from app.models.woocommerce_store import WooCommerceStore

    store = await db.get(WooCommerceStore, store_id)
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    allowed = {"name", "store_url", "consumer_key", "consumer_secret",
               "webhook_secret", "price_markup_percent", "is_active"}
    for key, value in fields.items():
        if key in allowed:
            setattr(store, key, value)

    await db.commit()
    return {"success": True, "id": store.id}


@store_router.delete("/{store_id}")
async def disconnect_wc_store(store_id: int, db: AsyncSession = Depends(get_db)):
    """Disconnect a WooCommerce store (soft delete via is_active=False)."""
    from app.models.woocommerce_store import WooCommerceStore

    store = await db.get(WooCommerceStore, store_id)
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    store.is_active = False
    store.sync_status = "disconnected"
    await db.commit()
    return {"success": True, "id": store.id, "status": "disconnected"}


@store_router.post("/{store_id}/test")
async def test_wc_store_connection(store_id: int, db: AsyncSession = Depends(get_db)):
    """Test connection for a specific WooCommerce store."""
    from app.models.woocommerce_store import WooCommerceStore

    store = await db.get(WooCommerceStore, store_id)
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    try:
        async with WooCommerceClient(
            store_url=store.store_url,
            consumer_key=store.consumer_key,
            consumer_secret=store.consumer_secret,
        ) as client:
            connected = await client.test_connection()
            if connected:
                store.sync_status = "healthy"
                await db.commit()
                return {"status": "connected", "store_url": store.store_url}
            else:
                store.sync_status = "error"
                await db.commit()
                return {"status": "failed", "message": "Could not connect"}
    except Exception as e:
        store.sync_status = "error"
        await db.commit()
        return {"status": "error", "message": str(e)}
