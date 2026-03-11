from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
from typing import List, Optional
from app.database import get_session
from app.core.config import Settings, get_settings
from app.core.security import get_current_username
from app.models.ebay import EbayListing
from app.models.platform_common import PlatformCommon
from app.models.product import Product
from app.services.ebay_service import EbayService

router = APIRouter(prefix="/admin", tags=["admin"])

@router.delete("/sync-events/{event_id}")
async def delete_sync_event(
    event_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_username)
):
    """Delete a specific sync event by ID"""
    try:
        result = await session.execute(
            text("DELETE FROM sync_event WHERE id = :id"),
            {"id": event_id}
        )
        await session.commit()

        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Sync event {event_id} not found")

        return {"message": f"Sync event {event_id} deleted successfully", "rows_affected": result.rowcount}
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/sync-events")
async def delete_sync_events_by_criteria(
    product_id: int = None,
    platform: str = None,
    status: str = None,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_username)
):
    """Delete sync events based on criteria"""
    if not any([product_id, platform, status]):
        raise HTTPException(status_code=400, detail="At least one filter criterion required")

    conditions = []
    params = {}

    if product_id:
        conditions.append("product_id = :product_id")
        params["product_id"] = product_id
    if platform:
        conditions.append("platform = :platform")
        params["platform"] = platform
    if status:
        conditions.append("status = :status")
        params["status"] = status

    where_clause = " AND ".join(conditions)

    try:
        # First count how many will be deleted
        count_result = await session.execute(
            text(f"SELECT COUNT(*) FROM sync_event WHERE {where_clause}"),
            params
        )
        count = count_result.scalar()

        if count == 0:
            return {"message": "No sync events found matching criteria", "rows_affected": 0}

        # Confirm large deletions
        if count > 10:
            # For safety, we'll just return the count and not delete
            return {
                "message": f"Found {count} sync events. Use specific IDs for large deletions.",
                "rows_found": count,
                "deleted": False
            }

        # Perform deletion
        result = await session.execute(
            text(f"DELETE FROM sync_event WHERE {where_clause}"),
            params
        )
        await session.commit()

        return {"message": f"Deleted {result.rowcount} sync events", "rows_affected": result.rowcount}
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/sync-events/query")
async def query_sync_events(
    product_id: int = None,
    platform: str = None,
    status: str = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_username)
):
    """Query sync events to see what would be deleted"""
    conditions = []
    params = {}

    if product_id:
        conditions.append("product_id = :product_id")
        params["product_id"] = product_id
    if platform:
        conditions.append("platform = :platform")
        params["platform"] = platform
    if status:
        conditions.append("status = :status")
        params["status"] = status

    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

    try:
        result = await session.execute(
            text(f"""
                SELECT id, product_id, platform, status, created_at, error_details
                FROM sync_event
                {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            {**params, "limit": limit}
        )

        events = []
        for row in result:
            events.append({
                "id": row[0],
                "product_id": row[1],
                "platform": row[2],
                "status": row[3],
                "created_at": str(row[4]),
                "error_details": row[5]
            })

        return {"count": len(events), "events": events}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/apply-ebay-template")
async def apply_ebay_template(
    dry_run: bool = False,
    limit: Optional[int] = None,
    settings: Settings = Depends(get_settings),
    current_user: str = Depends(get_current_username),
):
    """
    Batch-apply the CrazyLister HTML template to active eBay listings missing it.

    Query params:
      dry_run=true   Preview what would be revised without making eBay API calls.
      limit=N        Process at most N listings (useful for pilot runs).

    Returns JSON with per-item results and a summary.
    """
    results = {
        "dry_run": dry_run,
        "limit": limit,
        "found": 0,
        "updated": 0,
        "errors": 0,
        "items": [],
    }

    async with get_session() as db:
        service = EbayService(db, settings)

        stmt = (
            select(EbayListing, PlatformCommon, Product)
            .join(PlatformCommon, EbayListing.platform_id == PlatformCommon.id)
            .join(Product, PlatformCommon.product_id == Product.id)
            .where(PlatformCommon.platform_name == "ebay")
            .where(PlatformCommon.status == "ACTIVE")
            .where(Product.status == "ACTIVE")
            .where(EbayListing.listing_data["uses_crazylister"].astext == "false")
        )

        if limit:
            stmt = stmt.limit(limit)

        result = await db.execute(stmt)
        rows = result.all()
        results["found"] = len(rows)

        if dry_run:
            results["items"] = [
                {"item_id": listing.ebay_item_id, "sku": product.sku, "action": "would_revise"}
                for listing, pc, product in rows
            ]
            return results

        for listing, pc, product in rows:
            item_result = {"item_id": listing.ebay_item_id, "sku": product.sku}
            try:
                description_html = await service._render_ebay_template(product)
                await service.trading_api.revise_fixed_price_item(
                    item_id=listing.ebay_item_id,
                    Description=description_html,
                )
                item_result["status"] = "success"
                results["updated"] += 1
            except Exception as e:
                item_result["status"] = "error"
                item_result["error"] = str(e)
                results["errors"] += 1
            results["items"].append(item_result)

    return results