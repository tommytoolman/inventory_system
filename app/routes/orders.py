"""Orders routes - unified view of orders across all platforms."""
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text, select, func, or_, desc
from typing import Optional
from datetime import datetime, timedelta, timezone
import logging

from app.database import get_session
from app.core.templates import templates
from app.models.ebay_order import EbayOrder
from app.models.reverb_order import ReverbOrder
from app.models.shopify_order import ShopifyOrder

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def orders_list(
    request: Request,
    platform: str = Query("all", description="Filter by platform"),
    status: str = Query("all", description="Filter by order status"),
    search: Optional[str] = Query(None, description="Search by SKU, order ID, or customer"),
    days: int = Query(30, description="Number of days to look back"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    sort_by: str = Query("created_at", description="Column to sort by"),
    sort_order: str = Query("desc", description="Sort order: asc or desc"),
):
    """Unified orders list across all platforms."""

    async with get_session() as db:
        # Calculate date filter
        date_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

        # Build unified orders query using UNION
        # Each platform has different column names, so we normalize them
        # Note: ebay_orders uses created_time, shipping_country, buyer_user_id (no buyer_name)
        # Note: reverb_orders uses created_at, shipping_country_code, buyer_name
        query = text("""
            WITH unified_orders AS (
                -- eBay Orders
                SELECT
                    'ebay' as platform,
                    eo.id as order_id,
                    eo.order_id as external_order_id,
                    eo.order_status as status,
                    eo.created_time as created_at,
                    eo.total_amount,
                    COALESCE(eo.total_currency, 'GBP') as currency,
                    eo.primary_sku as sku,
                    COALESCE(
                        eo.raw_payload #>> '{{{{TransactionArray,Transaction,Item,Title}}}}',
                        eo.shipping_name
                    ) as title,
                    eo.quantity_purchased as quantity,
                    eo.shipping_name as customer_name,
                    NULL as customer_email,
                    eo.shipping_city,
                    eo.shipping_country as shipping_country_code,
                    eo.tracking_number,
                    eo.product_id
                FROM ebay_orders eo
                WHERE eo.created_time >= :date_cutoff

                UNION ALL

                -- Reverb Orders
                SELECT
                    'reverb' as platform,
                    ro.id as order_id,
                    ro.order_number as external_order_id,
                    ro.status,
                    ro.created_at,
                    ro.total_amount,
                    COALESCE(ro.total_currency, 'GBP') as currency,
                    ro.sku,
                    ro.title,
                    ro.quantity,
                    COALESCE(ro.buyer_name, ro.buyer_first_name || ' ' || ro.buyer_last_name) as customer_name,
                    ro.buyer_email as customer_email,
                    ro.shipping_city,
                    ro.shipping_country_code,
                    NULL as tracking_number,
                    ro.product_id
                FROM reverb_orders ro
                WHERE ro.created_at >= :date_cutoff

                UNION ALL

                -- Shopify Orders
                SELECT
                    'shopify' as platform,
                    so.id as order_id,
                    so.order_name as external_order_id,
                    so.financial_status as status,
                    so.created_at,
                    so.total_amount,
                    COALESCE(so.total_currency, 'GBP') as currency,
                    so.primary_sku as sku,
                    so.primary_title as title,
                    so.primary_quantity as quantity,
                    COALESCE(so.customer_first_name || ' ' || so.customer_last_name, so.shipping_name) as customer_name,
                    so.customer_email,
                    so.shipping_city,
                    so.shipping_country_code,
                    so.tracking_number,
                    so.product_id
                FROM shopify_orders so
                WHERE so.created_at >= :date_cutoff
            )
            SELECT * FROM unified_orders
            WHERE 1=1
            {platform_filter}
            {status_filter}
            {search_filter}
            ORDER BY {sort_column} {sort_direction}
            LIMIT :limit OFFSET :offset
        """.format(
            sort_column=sort_by if sort_by in ('created_at', 'total_amount', 'platform', 'status', 'customer_name', 'sku') else 'created_at',
            sort_direction='ASC' if sort_order == 'asc' else 'DESC',
            platform_filter="AND platform = :platform" if platform != "all" else "",
            status_filter="AND LOWER(status) LIKE :status_pattern" if status != "all" else "",
            search_filter="""AND (
                LOWER(sku) LIKE :search_pattern
                OR LOWER(external_order_id) LIKE :search_pattern
                OR LOWER(customer_name) LIKE :search_pattern
                OR LOWER(customer_email) LIKE :search_pattern
                OR LOWER(title) LIKE :search_pattern
            )""" if search else "",
        ))

        # Build params
        params = {
            "date_cutoff": date_cutoff,
            "limit": per_page,
            "offset": (page - 1) * per_page,
        }

        if platform != "all":
            params["platform"] = platform
        if status != "all":
            params["status_pattern"] = f"%{status.lower()}%"
        if search:
            params["search_pattern"] = f"%{search.lower()}%"

        result = await db.execute(query, params)
        orders = [dict(row._mapping) for row in result.fetchall()]

        # Get counts for summary
        count_query = text("""
            WITH unified_orders AS (
                SELECT 'ebay' as platform, eo.order_status as status, eo.total_amount, eo.created_time as created_at
                FROM ebay_orders eo WHERE eo.created_time >= :date_cutoff
                UNION ALL
                SELECT 'reverb' as platform, ro.status, ro.total_amount, ro.created_at
                FROM reverb_orders ro WHERE ro.created_at >= :date_cutoff
                UNION ALL
                SELECT 'shopify' as platform, so.financial_status as status, so.total_amount, so.created_at
                FROM shopify_orders so WHERE so.created_at >= :date_cutoff
            )
            SELECT
                platform,
                COUNT(*) as order_count,
                COALESCE(SUM(total_amount), 0) as total_revenue
            FROM unified_orders
            GROUP BY platform
        """)

        count_result = await db.execute(count_query, {"date_cutoff": date_cutoff})
        platform_stats = {row.platform: {"count": row.order_count, "revenue": float(row.total_revenue or 0)}
                         for row in count_result.fetchall()}

        # Total count for pagination
        total_query = text("""
            SELECT COUNT(*) FROM (
                SELECT 1 FROM ebay_orders WHERE created_time >= :date_cutoff
                UNION ALL
                SELECT 1 FROM reverb_orders WHERE created_at >= :date_cutoff
                UNION ALL
                SELECT 1 FROM shopify_orders WHERE created_at >= :date_cutoff
            ) t
        """)
        total_result = await db.execute(total_query, {"date_cutoff": date_cutoff})
        total_orders = total_result.scalar() or 0

    # Calculate total revenue
    total_revenue = sum(s.get("revenue", 0) for s in platform_stats.values())
    total_count = sum(s.get("count", 0) for s in platform_stats.values())

    # Pagination
    total_pages = (total_orders + per_page - 1) // per_page

    platform_options = [
        {"value": "all", "label": "All Platforms"},
        {"value": "ebay", "label": "eBay"},
        {"value": "reverb", "label": "Reverb"},
        {"value": "shopify", "label": "Shopify"},
    ]

    status_options = [
        {"value": "all", "label": "All Statuses"},
        {"value": "completed", "label": "Completed"},
        {"value": "paid", "label": "Paid"},
        {"value": "shipped", "label": "Shipped"},
        {"value": "cancelled", "label": "Cancelled"},
        {"value": "pending", "label": "Pending"},
    ]

    days_options = [
        {"value": 7, "label": "Last 7 days"},
        {"value": 30, "label": "Last 30 days"},
        {"value": 90, "label": "Last 90 days"},
        {"value": 365, "label": "Last year"},
    ]

    return templates.TemplateResponse("orders/list.html", {
        "request": request,
        "orders": orders,
        "platform_filter": platform,
        "platform_options": platform_options,
        "status_filter": status,
        "status_options": status_options,
        "search_query": search or "",
        "days": days,
        "days_options": days_options,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "total_orders": total_orders,
        "platform_stats": platform_stats,
        "total_revenue": total_revenue,
        "total_count": total_count,
        "sort_by": sort_by,
        "sort_order": sort_order,
    })


@router.get("/{platform}/{order_id}", response_class=HTMLResponse)
async def order_detail(
    request: Request,
    platform: str,
    order_id: int,
):
    """View detailed order information."""

    async with get_session() as db:
        order = None

        if platform == "ebay":
            result = await db.execute(
                select(EbayOrder).where(EbayOrder.id == order_id)
            )
            order = result.scalar_one_or_none()
        elif platform == "reverb":
            result = await db.execute(
                select(ReverbOrder).where(ReverbOrder.id == order_id)
            )
            order = result.scalar_one_or_none()
        elif platform == "shopify":
            result = await db.execute(
                select(ShopifyOrder).where(ShopifyOrder.id == order_id)
            )
            order = result.scalar_one_or_none()

    if not order:
        return templates.TemplateResponse("orders/not_found.html", {
            "request": request,
            "platform": platform,
            "order_id": order_id,
        }, status_code=404)

    return templates.TemplateResponse("orders/detail.html", {
        "request": request,
        "order": order,
        "platform": platform,
    })


@router.get("/api/stats")
async def orders_stats_api(
    days: int = Query(30, description="Number of days to look back"),
):
    """API endpoint for order statistics."""

    async with get_session() as db:
        date_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

        query = text("""
            WITH unified_orders AS (
                SELECT 'ebay' as platform, eo.total_amount, eo.created_time as created_at, eo.order_status as status
                FROM ebay_orders eo WHERE eo.created_time >= :date_cutoff
                UNION ALL
                SELECT 'reverb' as platform, ro.total_amount, ro.created_at, ro.status
                FROM reverb_orders ro WHERE ro.created_at >= :date_cutoff
                UNION ALL
                SELECT 'shopify' as platform, so.total_amount, so.created_at, so.financial_status as status
                FROM shopify_orders so WHERE so.created_at >= :date_cutoff
            )
            SELECT
                platform,
                COUNT(*) as order_count,
                COALESCE(SUM(total_amount), 0) as total_revenue,
                COUNT(CASE WHEN LOWER(status) LIKE '%complete%' OR LOWER(status) LIKE '%paid%' THEN 1 END) as completed_count
            FROM unified_orders
            GROUP BY platform
        """)

        result = await db.execute(query, {"date_cutoff": date_cutoff})
        stats = {
            row.platform: {
                "count": row.order_count,
                "revenue": float(row.total_revenue or 0),
                "completed": row.completed_count,
            }
            for row in result.fetchall()
        }

    return JSONResponse({
        "days": days,
        "platforms": stats,
        "totals": {
            "count": sum(s["count"] for s in stats.values()),
            "revenue": sum(s["revenue"] for s in stats.values()),
        }
    })
