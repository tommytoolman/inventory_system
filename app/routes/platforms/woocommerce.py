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
    """Simple in-memory cache for webhook delivery IDs with TTL eviction."""

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 86400):
        self._cache: OrderedDict[str, float] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds

    def seen(self, delivery_id: str) -> bool:
        """Return True if this delivery ID has already been processed."""
        self._evict_expired()
        if delivery_id in self._cache:
            return True
        self._cache[delivery_id] = time.time()
        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)
        return False

    def _evict_expired(self):
        cutoff = time.time() - self._ttl
        while self._cache:
            oldest_key = next(iter(self._cache))
            if self._cache[oldest_key] < cutoff:
                self._cache.pop(oldest_key)
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

    # Process in background
    background_tasks.add_task(
        _process_product_webhook_background,
        topic,
        payload,
        settings,
    )

    return {"status": "accepted"}


async def _process_product_webhook_background(
    topic: str,
    payload: Dict[str, Any],
    settings: Settings,
):
    """Process a WooCommerce product webhook in the background."""
    async with async_session() as db:
        try:
            service = WooCommerceService(db, settings)
            wc_product_id = str(payload.get("id", ""))

            if topic == "product.created":
                from app.services.woocommerce.importer import WooCommerceImporter
                importer = WooCommerceImporter(db)
                await importer._process_single_product(payload)
                await db.commit()
                logger.info(f"Webhook: imported new WC product {wc_product_id}")

            elif topic == "product.updated":
                from app.services.woocommerce.importer import WooCommerceImporter
                importer = WooCommerceImporter(db)
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

    background_tasks.add_task(
        _process_order_webhook_background,
        topic,
        payload,
        settings,
    )

    return {"status": "accepted"}


async def _process_order_webhook_background(
    topic: str,
    payload: Dict[str, Any],
    settings: Settings,
):
    """Process a WooCommerce order webhook in the background."""
    async with async_session() as db:
        try:
            service = WooCommerceService(db, settings)

            if topic in ("order.created", "order.updated"):
                # Process the single order from the webhook payload directly
                await service.import_single_order(payload)
                logger.info(f"Webhook: processed WC order {payload.get('id')} ({topic})")

        except Exception as e:
            await db.rollback()
            logger.error(f"Error processing WC order webhook ({topic}): {e}", exc_info=True)
