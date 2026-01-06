# app/routes/insights.py
"""
Insights Dashboard Routes

Provides velocity analytics, category benchmarks, and inventory health insights.
"""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.services.analytics_service import InventoryAnalyticsService
from app.core.security import require_auth

router = APIRouter(prefix="/insights", tags=["insights"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def insights_dashboard(
    request: Request,
    _: None = Depends(require_auth)
):
    """Main insights dashboard."""
    async with get_session() as db:
        service = InventoryAnalyticsService(db)
        dashboard_data = await service.get_insights_dashboard()

    return templates.TemplateResponse(
        "insights/dashboard.html",
        {
            "request": request,
            "data": dashboard_data,
            "page_title": "Inventory Insights",
        }
    )


@router.get("/category-benchmarks", response_class=HTMLResponse)
async def category_benchmarks(
    request: Request,
    period: str = "all_time",
    _: None = Depends(require_auth)
):
    """Category velocity benchmarks page."""
    async with get_session() as db:
        service = InventoryAnalyticsService(db)
        benchmarks = await service.compute_category_benchmarks(period_type=period)

    return templates.TemplateResponse(
        "insights/category_benchmarks.html",
        {
            "request": request,
            "benchmarks": benchmarks,
            "period": period,
            "page_title": "Category Benchmarks",
        }
    )


@router.get("/aged-inventory", response_class=HTMLResponse)
async def aged_inventory(
    request: Request,
    min_age: int = 90,
    limit: int = 50,
    _: None = Depends(require_auth)
):
    """Aged inventory analysis page."""
    async with get_session() as db:
        service = InventoryAnalyticsService(db)
        items = await service.get_aged_inventory(min_age_days=min_age, limit=limit)
        benchmarks = await service.compute_category_benchmarks()

    return templates.TemplateResponse(
        "insights/aged_inventory.html",
        {
            "request": request,
            "items": items,
            "benchmarks": benchmarks,
            "min_age": min_age,
            "page_title": "Aged Inventory Analysis",
        }
    )


@router.get("/api/dashboard")
async def api_dashboard(
    _: None = Depends(require_auth)
):
    """API endpoint for dashboard data."""
    async with get_session() as db:
        service = InventoryAnalyticsService(db)
        return await service.get_insights_dashboard()


@router.get("/api/category-benchmarks")
async def api_category_benchmarks(
    period: str = "all_time",
    _: None = Depends(require_auth)
):
    """API endpoint for category benchmarks."""
    async with get_session() as db:
        service = InventoryAnalyticsService(db)
        return await service.compute_category_benchmarks(period_type=period)


@router.get("/api/product/{product_id}/compare")
async def api_product_compare(
    product_id: int,
    _: None = Depends(require_auth)
):
    """API endpoint to compare product to category benchmark."""
    async with get_session() as db:
        service = InventoryAnalyticsService(db)
        return await service.compare_item_to_category(product_id)
