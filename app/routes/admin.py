from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import List
from app.database import get_session
from app.core.security import get_current_username

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