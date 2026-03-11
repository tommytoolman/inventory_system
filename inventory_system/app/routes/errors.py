"""
app/routes/errors.py

Endpoints for viewing and managing sync error records.

API:
  GET  /api/errors/sync          — paginated list (JSON)
  GET  /api/errors/sync/{id}     — single record detail (JSON)
  POST /api/errors/sync/{id}/resolve — mark resolved

UI:
  GET  /errors/sync              — HTML list page
  GET  /errors/sync/{id}         — HTML detail page
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.templates import templates
from app.database import get_session
from app.models.sync_error import SyncErrorRecord

logger = logging.getLogger(__name__)

router = APIRouter(tags=["errors"])


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------

@router.get("/api/errors/sync")
async def list_sync_errors(
    product_id: Optional[int] = None,
    platform: Optional[str] = None,
    resolved: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_session),
):
    """Return recent sync errors with optional filtering."""
    stmt = select(SyncErrorRecord).order_by(SyncErrorRecord.created_at.desc())
    if product_id is not None:
        stmt = stmt.where(SyncErrorRecord.product_id == product_id)
    if platform:
        stmt = stmt.where(SyncErrorRecord.platform == platform)
    if resolved is not None:
        stmt = stmt.where(SyncErrorRecord.resolved == resolved)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = stmt.limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "errors": [_serialise(r) for r in rows],
    }


@router.get("/api/errors/sync/{error_id}")
async def get_sync_error(error_id: str, db: AsyncSession = Depends(get_session)):
    """Return full error detail including stack trace."""
    record = await db.get(SyncErrorRecord, error_id.upper())
    if not record:
        raise HTTPException(status_code=404, detail=f"Error {error_id} not found")
    return _serialise(record, include_stack=True)


@router.post("/api/errors/sync/{error_id}/resolve")
async def resolve_sync_error(
    error_id: str,
    notes: Optional[str] = None,
    db: AsyncSession = Depends(get_session),
):
    """Mark an error as resolved with optional notes."""
    record = await db.get(SyncErrorRecord, error_id.upper())
    if not record:
        raise HTTPException(status_code=404, detail=f"Error {error_id} not found")
    record.resolved = True
    if notes:
        record.resolution_notes = notes
    await db.commit()
    return {"status": "resolved", "id": record.id}


# ---------------------------------------------------------------------------
# HTML UI
# ---------------------------------------------------------------------------

@router.get("/errors/sync")
async def sync_errors_page(
    request: Request,
    platform: Optional[str] = None,
    resolved: Optional[str] = None,
    db: AsyncSession = Depends(get_session),
):
    """HTML list of recent sync errors."""
    stmt = select(SyncErrorRecord).order_by(SyncErrorRecord.created_at.desc()).limit(100)
    if platform:
        stmt = stmt.where(SyncErrorRecord.platform == platform)
    if resolved == "true":
        stmt = stmt.where(SyncErrorRecord.resolved == True)
    elif resolved == "false":
        stmt = stmt.where(SyncErrorRecord.resolved == False)

    rows = (await db.execute(stmt)).scalars().all()

    # Unresolved count for badge
    unresolved_stmt = select(func.count()).where(SyncErrorRecord.resolved == False)
    unresolved_count = (await db.execute(unresolved_stmt)).scalar() or 0

    return templates.TemplateResponse(
        "errors/sync_errors.html",
        {
            "request": request,
            "errors": rows,
            "unresolved_count": unresolved_count,
            "filter_platform": platform or "",
            "filter_resolved": resolved or "",
        },
    )


@router.get("/errors/sync/{error_id}")
async def sync_error_detail_page(
    error_id: str,
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    """HTML detail view for a single sync error."""
    record = await db.get(SyncErrorRecord, error_id.upper())
    if not record:
        raise HTTPException(status_code=404, detail=f"Error {error_id} not found")
    return templates.TemplateResponse(
        "errors/sync_error_detail.html",
        {"request": request, "error": record},
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _serialise(r: SyncErrorRecord, include_stack: bool = False) -> dict:
    data = {
        "id": r.id,
        "product_id": r.product_id,
        "platform": r.platform,
        "operation": r.operation,
        "error_type": r.error_type,
        "error_message": r.error_message,
        "extra_context": r.extra_context,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "resolved": r.resolved,
        "resolution_notes": r.resolution_notes,
    }
    if include_stack:
        data["stack_trace"] = r.stack_trace
    return data
