"""Orders routes - unified view of orders across all platforms."""
from fastapi import APIRouter, Request, Query, Form
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text, select, func, or_, desc
from typing import Optional
from datetime import datetime, timedelta, timezone
import logging
import json

from app.database import get_session
from app.core.templates import templates
from app.models.ebay_order import EbayOrder
from app.models.reverb_order import ReverbOrder
from app.models.shopify_order import ShopifyOrder
from app.services.shipping.payload_builder import DHLPayloadBuilder, DestinationType
from app.services.shipping.carriers.dhl import DHLCarrier
from fastapi.responses import Response
import base64

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
                    CASE
                        WHEN so.fulfillment_status = 'fulfilled' THEN 'fulfilled'
                        WHEN so.financial_status IN ('refunded', 'voided') THEN so.financial_status
                        ELSE so.financial_status
                    END as status,
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


@router.get("/{platform}/{order_id}/ship", response_class=HTMLResponse)
async def ship_order(
    request: Request,
    platform: str,
    order_id: int,
):
    """Create shipping label for an order."""

    async with get_session() as db:
        order = None
        order_dict = {}

        if platform == "ebay":
            result = await db.execute(
                select(EbayOrder).where(EbayOrder.id == order_id)
            )
            order = result.scalar_one_or_none()
            if order:
                order_dict = {
                    'id': order.id,
                    'order_id': order.order_id,
                    'buyer_user_id': order.buyer_user_id,
                    'shipping_name': order.shipping_name,
                    'shipping_address': order.shipping_address,
                    'shipping_city': order.shipping_city,
                    'shipping_state': order.shipping_state,
                    'shipping_postal_code': order.shipping_postal_code,
                    'shipping_country': order.shipping_country,
                    'total_amount': float(order.total_amount) if order.total_amount else 0,
                    'total_currency': order.total_currency or 'GBP',
                    'primary_sku': order.primary_sku,
                    'tracking_number': order.tracking_number,
                    'order_status': order.order_status,
                }

        elif platform == "reverb":
            result = await db.execute(
                select(ReverbOrder).where(ReverbOrder.id == order_id)
            )
            order = result.scalar_one_or_none()
            if order:
                order_dict = {
                    'id': order.id,
                    'order_number': order.order_number,
                    'buyer_name': order.buyer_name,
                    'buyer_email': order.buyer_email,
                    'shipping_name': order.shipping_name,
                    'shipping_address': order.shipping_address,
                    'shipping_city': order.shipping_city,
                    'shipping_region': order.shipping_region,
                    'shipping_postal_code': order.shipping_postal_code,
                    'shipping_country_code': order.shipping_country_code,
                    'shipping_phone': order.shipping_phone,
                    'title': order.title,
                    'amount_product': float(order.amount_product) if order.amount_product else 0,
                    'amount_product_currency': order.amount_product_currency or 'GBP',
                    'total_amount': float(order.total_amount) if order.total_amount else 0,
                    'total_currency': order.total_currency or 'GBP',
                    'sku': order.sku,
                    'status': order.status,
                }

        elif platform == "shopify":
            result = await db.execute(
                select(ShopifyOrder).where(ShopifyOrder.id == order_id)
            )
            order = result.scalar_one_or_none()
            if order:
                order_dict = {
                    'id': order.id,
                    'order_name': order.order_name,
                    'shipping_name': order.shipping_name,
                    'shipping_address': order.shipping_address,
                    'shipping_city': order.shipping_city,
                    'shipping_province': order.shipping_province,
                    'shipping_postal_code': order.shipping_postal_code,
                    'shipping_country_code': order.shipping_country_code,
                    'total_amount': float(order.total_amount) if order.total_amount else 0,
                    'total_currency': order.total_currency or 'GBP',
                    'primary_sku': order.primary_sku,
                    'primary_title': order.primary_title,
                    'tracking_number': order.tracking_number,
                    'financial_status': order.financial_status,
                }

    if not order:
        return templates.TemplateResponse("orders/not_found.html", {
            "request": request,
            "platform": platform,
            "order_id": order_id,
        }, status_code=404)

    # Build DHL payload preview
    builder = DHLPayloadBuilder()

    # Get country code for destination classification
    if platform == "ebay":
        country_code = order_dict.get('shipping_country', 'GB')
    elif platform == "reverb":
        country_code = order_dict.get('shipping_country_code', 'GB')
    else:
        country_code = order_dict.get('shipping_country_code', 'GB')

    dest_type = builder.classify_destination(country_code)

    # Build receiver preview
    if platform == "ebay":
        receiver = builder._build_receiver_from_ebay(order_dict)
    elif platform == "reverb":
        receiver = builder._build_receiver_from_reverb(order_dict)
    else:
        # For Shopify, use similar logic to eBay
        receiver = builder._build_receiver_from_ebay(order_dict)

    # Get shipper preview
    shipper = builder._build_shipper_details()

    return templates.TemplateResponse("orders/ship.html", {
        "request": request,
        "order": order_dict,
        "platform": platform,
        "dest_type": dest_type.value,
        "dest_type_label": {
            'uk': 'UK Domestic',
            'eu': 'EU',
            'row': 'International (Rest of World)'
        }.get(dest_type.value, dest_type.value),
        "receiver": receiver,
        "shipper": shipper,
        "product_code": "N" if dest_type == DestinationType.UK_DOMESTIC else "P",
        "needs_customs": dest_type != DestinationType.UK_DOMESTIC,
    })


@router.post("/{platform}/{order_id}/ship/create")
async def create_shipping_label(
    request: Request,
    platform: str,
    order_id: int,
    weight: float = Form(5.0),
    length: int = Form(120),
    width: int = Form(50),
    height: int = Form(15),
    description: str = Form("Musical Instrument"),
    declared_value: float = Form(None),
    currency: str = Form("GBP"),
    hs_code: str = Form("9202900030"),
    request_pickup: bool = Form(False),
    test_mode: bool = Form(True),
):
    """Create a DHL shipping label for an order."""

    async with get_session() as db:
        order = None
        order_dict = {}

        # Fetch order based on platform
        if platform == "ebay":
            result = await db.execute(
                select(EbayOrder).where(EbayOrder.id == order_id)
            )
            order = result.scalar_one_or_none()
            if order:
                order_dict = {
                    'id': order.id,
                    'order_id': order.order_id,
                    'buyer_user_id': order.buyer_user_id,
                    'shipping_name': order.shipping_name,
                    'shipping_address': order.shipping_address,
                    'shipping_city': order.shipping_city,
                    'shipping_state': order.shipping_state,
                    'shipping_postal_code': order.shipping_postal_code,
                    'shipping_country': order.shipping_country,
                    'total_amount': float(order.total_amount) if order.total_amount else 0,
                    'total_currency': order.total_currency or 'GBP',
                    'primary_sku': order.primary_sku,
                }

        elif platform == "reverb":
            result = await db.execute(
                select(ReverbOrder).where(ReverbOrder.id == order_id)
            )
            order = result.scalar_one_or_none()
            if order:
                order_dict = {
                    'id': order.id,
                    'order_number': order.order_number,
                    'buyer_name': order.buyer_name,
                    'buyer_email': order.buyer_email,
                    'shipping_name': order.shipping_name,
                    'shipping_address': order.shipping_address,
                    'shipping_city': order.shipping_city,
                    'shipping_region': order.shipping_region,
                    'shipping_postal_code': order.shipping_postal_code,
                    'shipping_country_code': order.shipping_country_code,
                    'shipping_phone': order.shipping_phone,
                    'title': order.title,
                    'amount_product': float(order.amount_product) if order.amount_product else 0,
                    'amount_product_currency': order.amount_product_currency or 'GBP',
                    'total_amount': float(order.total_amount) if order.total_amount else 0,
                    'total_currency': order.total_currency or 'GBP',
                    'sku': order.sku,
                }

        elif platform == "shopify":
            result = await db.execute(
                select(ShopifyOrder).where(ShopifyOrder.id == order_id)
            )
            order = result.scalar_one_or_none()
            if order:
                order_dict = {
                    'id': order.id,
                    'order_name': order.order_name,
                    'shipping_name': order.shipping_name,
                    'shipping_address': order.shipping_address,
                    'shipping_city': order.shipping_city,
                    'shipping_province': order.shipping_province,
                    'shipping_postal_code': order.shipping_postal_code,
                    'shipping_country_code': order.shipping_country_code,
                    'total_amount': float(order.total_amount) if order.total_amount else 0,
                    'total_currency': order.total_currency or 'GBP',
                    'primary_sku': order.primary_sku,
                    'primary_title': order.primary_title,
                }

    if not order:
        return templates.TemplateResponse("orders/ship_result.html", {
            "request": request,
            "success": False,
            "error": f"Order not found: {platform}/{order_id}",
            "platform": platform,
            "order_id": order_id,
        }, status_code=404)

    # Build the DHL payload
    builder = DHLPayloadBuilder()

    # Use declared_value from form or fall back to order amount
    if declared_value is None:
        declared_value = order_dict.get('amount_product') or order_dict.get('total_amount') or 0

    # Build payload based on platform
    if platform == "reverb":
        # Add custom values from form to order dict for payload building
        order_dict['title'] = description  # Use form description
        order_dict['amount_product'] = declared_value
        order_dict['amount_product_currency'] = currency

        payload = builder.build_from_reverb_order(
            order=order_dict,
            weight_kg=weight,
            length_cm=length,
            width_cm=width,
            height_cm=height,
            request_pickup=request_pickup,
        )
    else:
        # eBay and Shopify use similar logic
        order_dict['total_amount'] = declared_value
        order_dict['total_currency'] = currency

        payload = builder.build_from_ebay_order(
            order=order_dict,
            weight_kg=weight,
            length_cm=length,
            width_cm=width,
            height_cm=height,
            request_pickup=request_pickup,
        )

    # Update HS code if customs required
    if payload.get("content", {}).get("isCustomsDeclarable"):
        export_dec = payload.get("content", {}).get("exportDeclaration", {})
        if export_dec and export_dec.get("lineItems"):
            export_dec["lineItems"][0]["commodityCodes"] = [
                {"typeCode": "outbound", "value": hs_code}
            ]

    # Validate payload before sending
    validation_errors = builder.validate_payload(payload)
    if validation_errors:
        return templates.TemplateResponse("orders/ship_result.html", {
            "request": request,
            "success": False,
            "error": "Validation errors: " + "; ".join(validation_errors),
            "platform": platform,
            "order_id": order_id,
            "order": order_dict,
        })

    # Create DHL carrier and call API
    dhl = DHLCarrier()

    # Override test mode based on form input
    if test_mode:
        dhl.base_url = "https://express.api.dhl.com/mydhlapi/test"
    else:
        dhl.base_url = "https://express.api.dhl.com/mydhlapi"

    logger.info(f"Creating DHL shipment for {platform}/{order_id} (test_mode={test_mode})")
    logger.debug(f"Payload: {json.dumps(payload, indent=2)}")

    result = await dhl.create_shipment(payload)

    if result.get("status") == "error":
        error_details = result.get("details", "Unknown error")
        # Try to parse DHL error response
        try:
            error_json = json.loads(error_details) if isinstance(error_details, str) else error_details
            if isinstance(error_json, dict):
                error_msg = error_json.get("detail") or error_json.get("message") or str(error_json)
            else:
                error_msg = str(error_details)
        except (json.JSONDecodeError, TypeError):
            error_msg = str(error_details)

        return templates.TemplateResponse("orders/ship_result.html", {
            "request": request,
            "success": False,
            "error": f"DHL API Error: {error_msg}",
            "platform": platform,
            "order_id": order_id,
            "order": order_dict,
            "test_mode": test_mode,
        })

    # Success! Extract tracking number and documents
    tracking_number = result.get("shipmentTrackingNumber")
    documents = result.get("documents", [])

    # Update order with tracking number
    if tracking_number and not test_mode:
        async with get_session() as db:
            if platform == "ebay":
                await db.execute(
                    text("UPDATE ebay_orders SET tracking_number = :tn WHERE id = :id"),
                    {"tn": tracking_number, "id": order_id}
                )
            elif platform == "reverb":
                await db.execute(
                    text("UPDATE reverb_orders SET tracking_number = :tn WHERE id = :id"),
                    {"tn": tracking_number, "id": order_id}
                )
            elif platform == "shopify":
                await db.execute(
                    text("UPDATE shopify_orders SET tracking_number = :tn WHERE id = :id"),
                    {"tn": tracking_number, "id": order_id}
                )
            await db.commit()
            logger.info(f"Updated {platform} order {order_id} with tracking number {tracking_number}")

    # Extract label PDF if available
    label_pdf = None
    waybill_pdf = None
    invoice_pdf = None

    for doc in documents:
        doc_type = doc.get("typeCode")
        content = doc.get("content")
        if content:
            if doc_type == "label":
                label_pdf = content
            elif doc_type == "waybillDoc":
                waybill_pdf = content
            elif doc_type == "invoice":
                invoice_pdf = content

    return templates.TemplateResponse("orders/ship_result.html", {
        "request": request,
        "success": True,
        "tracking_number": tracking_number,
        "platform": platform,
        "order_id": order_id,
        "order": order_dict,
        "test_mode": test_mode,
        "label_pdf": label_pdf,
        "waybill_pdf": waybill_pdf,
        "invoice_pdf": invoice_pdf,
        "estimated_delivery": result.get("estimatedDeliveryDate", {}).get("estimatedDeliveryDate"),
    })


@router.get("/{platform}/{order_id}/ship/label/{doc_type}")
async def get_shipping_label(
    platform: str,
    order_id: int,
    doc_type: str,
    content: str = Query(..., description="Base64 encoded PDF content"),
):
    """Serve a shipping label/document as PDF download."""
    try:
        pdf_bytes = base64.b64decode(content)
        filename = f"dhl_{doc_type}_{platform}_{order_id}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    except Exception as e:
        logger.error(f"Error decoding PDF: {e}")
        return JSONResponse({"error": "Invalid PDF content"}, status_code=400)
