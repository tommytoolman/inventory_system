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

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.woocommerce_service import WooCommerceService
from app.services.websockets.manager import manager
from app.services.activity_logger import ActivityLogger
from app.dependencies import get_db
from app.core.config import Settings, get_settings
from app.core.exceptions import WooCommerceAPIError

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
        db,
        settings,
        sync_run_id,
    )

    return {
        "status": "success",
        "message": "WooCommerce sync started",
        "sync_run_id": str(sync_run_id),
    }


async def run_woocommerce_sync_background(
    db: AsyncSession,
    settings: Settings,
    sync_run_id: uuid.UUID,
):
    """Run WooCommerce sync in background with WebSocket updates."""
    logger.info(f"Starting WooCommerce sync background task for run_id: {sync_run_id}")

    activity_logger = ActivityLogger(db)

    try:
        # Send start notification
        await manager.broadcast({
            "type": "sync_started",
            "platform": "woocommerce",
            "sync_run_id": str(sync_run_id),
            "timestamp": datetime.now().isoformat(),
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

            # Send success notification
            await manager.broadcast({
                "type": "sync_completed",
                "platform": "woocommerce",
                "status": "success",
                "data": result,
                "timestamp": datetime.now().isoformat(),
            })

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
                "timestamp": datetime.now().isoformat(),
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
            "timestamp": datetime.now().isoformat(),
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
    except WooCommerceAPIError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error publishing to WooCommerce: {e}", exc_info=True)
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
    except WooCommerceAPIError as e:
        raise HTTPException(status_code=404, detail=str(e))
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
        client = WooCommerceClient()
        connected = await client.test_connection()
        if connected:
            return {"status": "connected", "store_url": settings.WC_STORE_URL}
        else:
            return {"status": "failed", "message": "Could not connect to WooCommerce API"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
