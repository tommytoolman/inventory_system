# app/routes/platforms/shopify.py
"""
API routes for Shopify platform integration.

This module provides endpoints for managing Shopify products, including:
- Syncing inventory from Shopify
- Processing order webhooks
- Publishing products
- Updating inventory
"""

import logging
import uuid
import hmac
import hashlib
import base64

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request, Header
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, Optional
from datetime import datetime

from app.services.shopify_service import ShopifyService
from app.services.websockets.manager import manager
from app.services.activity_logger import ActivityLogger
from app.dependencies import get_db
from app.core.config import Settings, get_settings
from app.core.exceptions import ShopifyAPIError

router = APIRouter(prefix="/api", tags=["shopify"])

logger = logging.getLogger(__name__)

@router.post("/sync/shopify")
async def sync_shopify(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """Run Shopify read sync - download latest inventory and update local database"""
    sync_run_id = uuid.uuid4()
    logger.info(f"Initiating standalone Shopify sync with run_id: {sync_run_id}")
    
    background_tasks.add_task(
        run_shopify_sync_background,
        db,
        settings,
        sync_run_id
    )
    
    return {
        "status": "success", 
        "message": "Shopify sync started", 
        "sync_run_id": str(sync_run_id)
    }

async def run_shopify_sync_background(
    db: AsyncSession, 
    settings: Settings, 
    sync_run_id: uuid.UUID
):
    """Run Shopify sync in background with WebSocket updates"""
    logger.info(f"Starting Shopify sync through background task for run_id: {sync_run_id}")
    
    # Add activity logger
    activity_logger = ActivityLogger(db)
    
    try:
        # Log sync start — commented out to reduce activity_log noise (still visible in Railway logs)
        # await activity_logger.log_activity(
        #     action="sync_start",
        #     entity_type="platform",
        #     entity_id="shopify",
        #     platform="shopify",
        #     details={"status": "started", "sync_run_id": str(sync_run_id)}
        # )
        
        # Send start notification
        await manager.broadcast({
            "type": "sync_started",
            "platform": "shopify",
            "sync_run_id": str(sync_run_id),
            "timestamp": datetime.now().isoformat()
        })
        
        # Initialize Shopify service
        shopify_service = ShopifyService(db, settings)
        result = await shopify_service.run_import_process(sync_run_id)
        
        if result.get('status') == 'success' or 'total_from_shopify' in result:
            # Update last_sync timestamp for Shopify platform entries
            update_query = text("""
                UPDATE platform_common 
                SET last_sync = timezone('utc', now()),
                    sync_status = 'SYNCED'
                WHERE platform_name = 'shopify'
            """)
            await db.execute(update_query)
            
            # Log successful sync
            await activity_logger.log_activity(
                action="sync",
                entity_type="platform", 
                entity_id="shopify",
                platform="shopify",
                details={
                    "status": "success",
                    "total": result.get('total_from_shopify', 0),
                    "created": result.get('created', 0),
                    "updated": result.get('updated', 0),
                    "removed": result.get('removed', 0),
                    "errors": result.get('errors', 0),
                    "events_logged": result.get('events_logged', 0),
                    "icon": "✅",
                    "message": f"Synced Shopify ({result.get('total_from_shopify', 0)} items)"
                }
            )
            
            # Send success notification
            await manager.broadcast({
                "type": "sync_completed",
                "platform": "shopify",
                "status": "success",
                "data": result,
                "timestamp": datetime.now().isoformat()
            })
            
            logger.info(f"Shopify import process result: {result}")
            logger.info(f"Background Shopify sync completed for run_id: {sync_run_id}")
            
        else:
            # Log failed sync
            await activity_logger.log_activity(
                action="sync_error",
                entity_type="platform",
                entity_id="shopify", 
                platform="shopify",
                details={
                    "error": result.get('message', 'Unknown error'),
                    "sync_run_id": str(sync_run_id)
                }
            )
            
            # Send error notification
            await manager.broadcast({
                "type": "sync_completed",
                "platform": "shopify",
                "status": "error",
                "message": result.get('message', 'Unknown error'),
                "timestamp": datetime.now().isoformat()
            })
            
            logger.error(f"Shopify sync error: {result.get('message', 'Unknown error')}")
        
        # Commit the activity logging
        await db.commit()
            
    except Exception as e:
        await db.rollback()
        error_message = str(e)
        logger.exception(f"Shopify sync background task failed: {error_message}")
        
        # Log exception
        await activity_logger.log_activity(
            action="sync_error",
            entity_type="platform",
            entity_id="shopify",
            platform="shopify", 
            details={
                "error": error_message,
                "sync_run_id": str(sync_run_id)
            }
        )
        await db.commit()
        
        # Send error notification
        await manager.broadcast({
            "type": "sync_completed",
            "platform": "shopify",
            "status": "error",
            "message": error_message,
            "timestamp": datetime.now().isoformat()
        })

@router.post("/webhooks/orders")
async def handle_order_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_shopify_hmac_sha256: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """
    Handle order webhook from Shopify.
    
    This endpoint receives order notifications from Shopify when an order is placed.
    It validates the webhook signature and processes the order.
    """
    # Get raw body for HMAC validation
    body = await request.body()
    
    # Validate webhook signature
    if not verify_shopify_webhook(body, x_shopify_hmac_sha256, settings.SHOPIFY_WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    
    # Parse the JSON payload
    payload = await request.json()
    
    # Process in background to avoid timeout
    background_tasks.add_task(
        process_order_webhook_background,
        payload,
        db,
        settings
    )
    
    return {"status": "accepted"}

async def process_order_webhook_background(
    payload: Dict[str, Any],
    db: AsyncSession,
    settings: Settings
):
    """Process order webhook in background"""
    logger.info(f"Processing Shopify order webhook for order {payload.get('id')}")
    
    try:
        service = ShopifyService(db, settings)
        await service.process_order_webhook(payload)
        
        # Log the order processing
        activity_logger = ActivityLogger(db)
        await activity_logger.log_activity(
            action="order_processed",
            entity_type="order",
            entity_id=str(payload.get('id')),
            platform="shopify",
            details={
                "order_number": payload.get('order_number'),
                "total": payload.get('total_price'),
                "items": len(payload.get('line_items', []))
            }
        )
        await db.commit()
        
    except Exception as e:
        logger.error(f"Error processing Shopify order webhook: {e}", exc_info=True)

@router.post("/products/{product_id}/publish")
async def publish_to_shopify(
    product_id: int,
    shopify_data: Optional[Dict[str, Any]] = None,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """
    Publish a product to Shopify.
    
    This creates or updates a product on Shopify.
    
    Args:
        product_id: Internal product ID
        shopify_data: Optional custom data for Shopify
        
    Returns:
        Success status and Shopify product ID
    """
    try:
        service = ShopifyService(db, settings)
        result = await service.publish_product(product_id, shopify_data or {})
        return result
    except Exception as e:
        logger.error(f"Error publishing to Shopify: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/products/{external_id}/inventory")
async def update_shopify_inventory(
    external_id: str,
    quantity: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """
    Update inventory for a Shopify product.
    
    Args:
        external_id: Shopify product ID
        quantity: New inventory level
        
    Returns:
        Success status
    """
    if quantity < 0:
        raise HTTPException(status_code=400, detail="Quantity cannot be negative")
    
    try:
        service = ShopifyService(db, settings)
        success = await service.update_inventory(external_id, quantity)
        return {"success": success}
    except ShopifyAPIError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/products/{external_id}")
async def get_shopify_product(
    external_id: str,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """
    Get product details from Shopify.
    
    Args:
        external_id: Shopify product ID
        
    Returns:
        Product data from Shopify
    """
    try:
        service = ShopifyService(db, settings)
        product = await service.get_product(external_id)
        return product
    except ShopifyAPIError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/shopify/products/{product_id}/archive")
async def archive_shopify_product(
    product_id: str,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """Archive (mark as sold) a Shopify product"""
    try:
        # Initialize Shopify service
        shopify_service = ShopifyService(db, settings)

        # Mark the item as sold (which archives it in Shopify)
        success = await shopify_service.mark_item_as_sold(product_id)

        if success:
            # Update local database status
            query = text("""
                UPDATE platform_common pc
                SET status = 'archived',
                    last_sync = CURRENT_TIMESTAMP
                WHERE pc.platform_name = 'shopify'
                AND pc.external_id = :product_id
            """)
            await db.execute(query, {"product_id": product_id})

            # Log activity
            activity_logger = ActivityLogger(db)
            await activity_logger.log_activity(
                action="archive_listing",
                entity_type="listing",
                entity_id=product_id,
                platform="shopify",
                details={"status": "archived", "method": "manual_ui"}
            )

            await db.commit()

            return {"success": True, "message": f"Shopify product {product_id} archived successfully"}
        else:
            raise HTTPException(status_code=400, detail="Failed to archive product on Shopify")

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error archiving Shopify product {product_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

def verify_shopify_webhook(
    body: bytes,
    signature: Optional[str],
    secret: str
) -> bool:
    """
    Verify Shopify webhook signature.

    Args:
        body: Raw request body
        signature: X-Shopify-Hmac-Sha256 header value
        secret: Webhook secret from Shopify

    Returns:
        True if signature is valid
    """
    if not signature:
        return False

    # Calculate expected signature
    hash = hmac.new(
        secret.encode('utf-8'),
        body,
        hashlib.sha256
    )
    expected = base64.b64encode(hash.digest()).decode()

    # Compare signatures
    return hmac.compare_digest(expected, signature)