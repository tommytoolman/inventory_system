from fastapi import APIRouter, Request, Depends, Query, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
from sqlalchemy.orm import selectinload
import json
from typing import Optional, List, Dict, Any
from datetime import datetime
from collections import Counter
from app.database import get_session
from app.core.templates import templates
from app.core.config import Settings, get_settings
from app.services.reconciliation_service import process_reconciliation
from app.models import SyncEvent
from app.models.product import Product, ProductStatus
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.models.ebay import EbayListing
from app.models.shopify import ShopifyListing
from app.models.vr import VRListing
from scripts.product_matcher import ProductMatcher
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def reports_index(request: Request):
    """Main reports dashboard"""
    return templates.TemplateResponse("reports/index.html", {
        "request": request
    })


@router.get("/status-mismatches", response_class=HTMLResponse)
async def status_mismatches_report(
    request: Request,
    platform_a: Optional[str] = Query("reverb"),  # Default to reverb
    platform_b: Optional[str] = Query("vr")       # Default to vr
):
    """Status mismatches report with filtering"""
    
    async with get_session() as db:
        # Real status mismatch query with proper JOIN logic
        mismatch_query = text("""
        SELECT 
            p.id,
            p.sku,
            p.brand,
            p.model,
            p.base_price as price,
            p.primary_image,
            
            -- Raw statuses
            CASE 
                WHEN :platform_a = 'reverb' THEN rl_a.reverb_state
                WHEN :platform_a = 'vr' THEN vl_a.vr_state
                WHEN :platform_a = 'ebay' THEN el_a.listing_status
                WHEN :platform_a = 'shopify' THEN sl_a.status
            END as raw_status_a,
            CASE 
                WHEN :platform_b = 'reverb' THEN rl_b.reverb_state
                WHEN :platform_b = 'vr' THEN vl_b.vr_state
                WHEN :platform_b = 'ebay' THEN el_b.listing_status
                WHEN :platform_b = 'shopify' THEN sl_b.status
            END as raw_status_b,
            
            -- Mapped statuses
            psm_a.central_status as central_status_a,
            psm_b.central_status as central_status_b
            
        FROM products p
        -- Join to Platform A
        INNER JOIN platform_common pc_a ON p.id = pc_a.product_id AND pc_a.platform_name = :platform_a
        -- Join to Platform B
        INNER JOIN platform_common pc_b ON p.id = pc_b.product_id AND pc_b.platform_name = :platform_b
        
        -- Platform listings (CORRECTED JOIN LOGIC)
        LEFT JOIN reverb_listings rl_a ON (:platform_a = 'reverb' AND pc_a.external_id = rl_a.reverb_listing_id)
        LEFT JOIN reverb_listings rl_b ON (:platform_b = 'reverb' AND pc_b.external_id = rl_b.reverb_listing_id)
        LEFT JOIN vr_listings vl_a ON (:platform_a = 'vr' AND pc_a.external_id = vl_a.vr_listing_id)
        LEFT JOIN vr_listings vl_b ON (:platform_b = 'vr' AND pc_b.external_id = vl_b.vr_listing_id)
        LEFT JOIN ebay_listings el_a ON (:platform_a = 'ebay' AND pc_a.external_id = el_a.ebay_item_id)
        LEFT JOIN ebay_listings el_b ON (:platform_b = 'ebay' AND pc_b.external_id = el_b.ebay_item_id)
        LEFT JOIN shopify_listings sl_a ON (:platform_a = 'shopify' AND pc_a.id = sl_a.platform_id)
        LEFT JOIN shopify_listings sl_b ON (:platform_b = 'shopify' AND pc_b.id = sl_b.platform_id)
        
        -- Status mappings
        LEFT JOIN platform_status_mappings psm_a ON psm_a.platform_name = :platform_a AND (
            (:platform_a = 'reverb' AND psm_a.platform_status = rl_a.reverb_state) OR
            (:platform_a = 'vr' AND psm_a.platform_status = vl_a.vr_state) OR
            (:platform_a = 'ebay' AND psm_a.platform_status = el_a.listing_status) OR
            (:platform_a = 'shopify' AND psm_a.platform_status = sl_a.status)
        )
        LEFT JOIN platform_status_mappings psm_b ON psm_b.platform_name = :platform_b AND (
            (:platform_b = 'reverb' AND psm_b.platform_status = rl_b.reverb_state) OR
            (:platform_b = 'vr' AND psm_b.platform_status = vl_b.vr_state) OR
            (:platform_b = 'ebay' AND psm_b.platform_status = el_b.listing_status) OR
            (:platform_b = 'shopify' AND psm_b.platform_status = sl_b.status)
        )
        
        -- ONLY show real mapped status mismatches
        WHERE psm_a.central_status != psm_b.central_status
        AND psm_a.central_status IS NOT NULL 
        AND psm_b.central_status IS NOT NULL
        
        ORDER BY p.base_price DESC
        LIMIT 500;
        """)
        
        result = await db.execute(mismatch_query, {
            "platform_a": platform_a, 
            "platform_b": platform_b
        })
        mismatches = [dict(row._mapping) for row in result.fetchall()]
        
        return templates.TemplateResponse("reports/status_mismatches.html", {
            "request": request,
            "summary_stats": [],  # Remove summary for now
            "detailed_mismatches": mismatches,
            "platform_a": platform_a,
            "platform_b": platform_b,
            "total_value": sum(float(item['price'] or 0) for item in mismatches),
            "platforms": ["reverb", "ebay", "shopify", "vr"]
        })


@router.get("/listing-health", response_class=HTMLResponse)
async def listing_health_report(
    request: Request,
    status: Optional[str] = Query("ALL", description="Filter by product status"),
    issues_only: bool = Query(False, description="Show only rows with warnings or errors"),
    limit: Optional[str] = Query("100", description="Maximum rows to display (or ALL)")
):
    """Traffic-light view of product listing health across platforms."""

    platform_defs = [
        ("shopify", "Shopify", "shopify_listing"),
        ("reverb", "Reverb", "reverb_listing"),
        ("ebay", "eBay", "ebay_listing"),
        ("vr", "Vintage & Rare", "vr_listing"),
    ]

    def _determine_status(errors: List[str], warnings: List[str]) -> str:
        if errors:
            return "error"
        if warnings:
            return "warning"
        return "ok"

    def _evaluate_core(product: Product) -> Dict[str, Any]:
        errors: List[str] = []
        warnings: List[str] = []

        title_candidate = product.title or product.generate_title()
        if not title_candidate:
            errors.append("Missing product title")

        if not product.category:
            errors.append("Missing category")

        if product.is_stocked_item:
            if product.quantity is None:
                warnings.append("Quantity not set for stocked item")
            elif product.quantity <= 0:
                errors.append("Stocked item has zero quantity")

        if not product.description:
            warnings.append("No description")

        if product.status == ProductStatus.ACTIVE and not product.shipping_profile_id:
            warnings.append("No shipping profile")

        status_value = _determine_status(errors, warnings)
        issues = errors + warnings
        return {
            "status": status_value,
            "issues": issues,
        }

    def _evaluate_media(product: Product) -> Dict[str, Any]:
        errors: List[str] = []
        warnings: List[str] = []

        primary_missing = not bool(product.primary_image)
        gallery_missing = not bool(product.additional_images)

        if primary_missing and gallery_missing:
            errors.append("Missing ALL images")
        else:
            if primary_missing:
                errors.append("Missing primary image")
            if gallery_missing:
                warnings.append("No Additional Images")

        status_value = _determine_status(errors, warnings)
        issues = errors + warnings
        return {
            "status": status_value,
            "issues": issues,
        }

    def _evaluate_platform(product: Product, platform_name: str, label: str, attr: str) -> Dict[str, Any]:
        commons = [pc for pc in product.platform_listings if (pc.platform_name or "").lower() == platform_name]
        if not commons:
            return {
                "label": label,
                "status": "not_listed",
                "issues": [],
            }

        common = commons[0]
        errors: List[str] = []
        warnings: List[str] = []

        if not common.external_id:
            errors.append("Missing external ID")
        if not common.listing_url:
            warnings.append("Missing listing URL")

        sync_state = (common.sync_status or "").lower()
        if sync_state not in {"synced", "ok", "success"}:
            warnings.append(f"Sync status is '{common.sync_status or 'unknown'}'")

        listing = getattr(common, attr, None)
        if listing is None:
            errors.append("No platform listing record")
        else:
            if platform_name == "shopify" and not getattr(listing, "category_gid", None):
                warnings.append("Category missing")
            if platform_name == "ebay" and not getattr(listing, "listing_status", None):
                warnings.append("eBay listing status unknown")
            if platform_name == "reverb" and not getattr(listing, "reverb_state", None):
                warnings.append("Reverb state missing")

        status_value = _determine_status(errors, warnings)
        issues = errors + warnings
        return {
            "label": label,
            "status": status_value,
            "issues": issues,
            "platform_common": common,
        }

    status_filter = (status or "ALL").upper()

    async with get_session() as db:
        query = (
            select(Product)
            .options(
                selectinload(Product.platform_listings)
                .selectinload(PlatformCommon.shopify_listing),
                selectinload(Product.platform_listings)
                .selectinload(PlatformCommon.reverb_listing),
                selectinload(Product.platform_listings)
                .selectinload(PlatformCommon.ebay_listing),
                selectinload(Product.platform_listings)
                .selectinload(PlatformCommon.vr_listing),
            )
            .order_by(Product.created_at.desc())
        )

        limit_param = (limit or "100").upper()
        limit_value: Optional[int]
        if limit_param == "ALL":
            limit_value = None
        else:
            try:
                limit_value = max(1, min(500, int(limit_param)))
                limit_param = str(limit_value)
            except ValueError:
                limit_value = 100
                limit_param = "100"

        if limit_value is not None:
            query = query.limit(limit_value)

        if status_filter != "ALL":
            try:
                status_enum = ProductStatus[status_filter]
                query = query.where(Product.status == status_enum)
            except KeyError:
                logger.warning("Unknown status filter '%s' supplied to listing health report", status_filter)

        products = (await db.execute(query)).scalars().all()

        status_priority = {"error": 0, "warning": 1, "ok": 2, "not_listed": 3}

        health_rows: List[Dict[str, Any]] = []
        for product in products:
            core = _evaluate_core(product)
            media = _evaluate_media(product)

            platforms = {
                name: _evaluate_platform(product, name, label, attr)
                for name, label, attr in platform_defs
            }

            statuses_to_consider = [core["status"], media["status"]]
            statuses_to_consider.extend(
                info["status"]
                for info in platforms.values()
                if info["status"] != "not_listed"
            )

            if statuses_to_consider:
                overall_status = min(statuses_to_consider, key=lambda s: status_priority.get(s, 4))
            else:
                overall_status = "not_listed"

            health_rows.append({
                "product": product,
                "core": core,
                "media": media,
                "platforms": platforms,
                "overall_status": overall_status,
            })

        if issues_only:
            health_rows = [row for row in health_rows if row["overall_status"] in {"warning", "error", "not_listed"}]

        status_totals = Counter(row["overall_status"] for row in health_rows)
        warning_count = sum(
            status_totals.get(key, 0) for key in ("warning", "error", "not_listed")
        )
        healthy_count = status_totals.get("ok", 0)

        status_options = ["ALL"] + list(ProductStatus.__members__.keys())
        status_labels = {
            "ok": "Healthy",
            "warning": "Warning",
            "error": "Issue",
            "not_listed": "Not listed",
        }
        status_classes = {
            "ok": "bg-green-100 text-green-800",
            "warning": "bg-yellow-100 text-yellow-800",
            "error": "bg-red-100 text-red-800",
            "not_listed": "bg-gray-100 text-gray-600",
        }

        product_status_classes = {
            "ACTIVE": "bg-green-100 text-green-800",
            "DRAFT": "bg-yellow-100 text-yellow-800",
            "SOLD": "bg-red-100 text-red-800",
            "ARCHIVED": "bg-purple-100 text-purple-800",
        }

        return templates.TemplateResponse("reports/listing_health_report.html", {
            "request": request,
            "rows": health_rows,
            "status_filter": status_filter,
            "status_options": status_options,
            "issues_only": issues_only,
            "status_labels": status_labels,
            "status_classes": status_classes,
            "platform_defs": platform_defs,
            "product_status_classes": product_status_classes,
            "warning_count": warning_count,
            "healthy_count": healthy_count,
            "limit_param": limit_param,
        })


async def get_status_mismatch_summary(db: AsyncSession) -> List[Dict]:
    """Get summary of status mismatches across all platform pairs"""
    
    query = text("""
    WITH platform_pairs AS (
        SELECT DISTINCT 
            pc1.platform_name as platform_a,
            pc2.platform_name as platform_b,
            COUNT(*) as total_shared_products
        FROM platform_common pc1
        INNER JOIN platform_common pc2 ON pc1.product_id = pc2.product_id
        WHERE pc1.platform_name < pc2.platform_name
        GROUP BY pc1.platform_name, pc2.platform_name
    ),
    status_mismatches AS (
        SELECT 
            pc1.platform_name as platform_a,
            pc2.platform_name as platform_b,
            COUNT(*) as mismatch_count,
            SUM(COALESCE(p.base_price, 0)) as total_mismatch_value
        FROM platform_common pc1
        INNER JOIN platform_common pc2 ON pc1.product_id = pc2.product_id
        INNER JOIN products p ON pc1.product_id = p.id
        LEFT JOIN reverb_listings rl_a ON (pc1.platform_name = 'reverb' AND CONCAT('REV-', pc1.external_id) = rl_a.reverb_listing_id)
        LEFT JOIN ebay_listings el_a ON (pc1.platform_name = 'ebay' AND pc1.external_id = el_a.ebay_item_id)
        LEFT JOIN shopify_listings sl_a ON (pc1.platform_name = 'shopify' AND pc1.id = sl_a.platform_id)
        LEFT JOIN vr_listings vl_a ON (pc1.platform_name = 'vr' AND pc1.external_id = vl_a.vr_listing_id)
        LEFT JOIN reverb_listings rl_b ON (pc2.platform_name = 'reverb' AND CONCAT('REV-', pc2.external_id) = rl_b.reverb_listing_id)
        LEFT JOIN ebay_listings el_b ON (pc2.platform_name = 'ebay' AND pc2.external_id = el_b.ebay_item_id)
        LEFT JOIN shopify_listings sl_b ON (pc2.platform_name = 'shopify' AND pc2.id = sl_b.platform_id)
        LEFT JOIN vr_listings vl_b ON (pc2.platform_name = 'vr' AND pc2.external_id = vl_b.vr_listing_id)
        LEFT JOIN platform_status_mappings psm_a ON (
            (pc1.platform_name = 'reverb' AND psm_a.platform_name = 'reverb' AND psm_a.platform_status = rl_a.reverb_state) OR
            (pc1.platform_name = 'ebay' AND psm_a.platform_name = 'ebay' AND psm_a.platform_status = el_a.listing_status) OR
            (pc1.platform_name = 'shopify' AND psm_a.platform_name = 'shopify' AND psm_a.platform_status = sl_a.status) OR
            (pc1.platform_name = 'vr' AND psm_a.platform_name = 'vr' AND psm_a.platform_status = vl_a.vr_state)
        )
        LEFT JOIN platform_status_mappings psm_b ON (
            (pc2.platform_name = 'reverb' AND psm_b.platform_name = 'reverb' AND psm_b.platform_status = rl_b.reverb_state) OR
            (pc2.platform_name = 'ebay' AND psm_b.platform_name = 'ebay' AND psm_b.platform_status = el_b.listing_status) OR
            (pc2.platform_name = 'shopify' AND psm_b.platform_name = 'shopify' AND psm_b.platform_status = sl_b.status) OR
            (pc2.platform_name = 'vr' AND psm_b.platform_name = 'vr' AND psm_b.platform_status = vl_b.vr_state)
        )
        WHERE pc1.platform_name < pc2.platform_name
        AND psm_a.central_status != psm_b.central_status
        GROUP BY pc1.platform_name, pc2.platform_name
    )
    SELECT 
        pp.platform_a,
        pp.platform_b,
        pp.total_shared_products,
        COALESCE(sm.mismatch_count, 0) as mismatch_count,
        COALESCE(sm.total_mismatch_value, 0) as total_mismatch_value,
        ROUND(COALESCE(sm.mismatch_count, 0) * 100.0 / pp.total_shared_products, 1) as mismatch_percentage
    FROM platform_pairs pp
    LEFT JOIN status_mismatches sm ON pp.platform_a = sm.platform_a AND pp.platform_b = sm.platform_b
    ORDER BY COALESCE(sm.mismatch_count, 0) DESC;
    """)
    
    result = await db.execute(query)
    return [dict(row._mapping) for row in result.fetchall()]


async def get_detailed_status_mismatches(db: AsyncSession, platform_a: str, platform_b: str) -> List[Dict]:
    """Get detailed status mismatches for specific platform pair"""
    
    query = text("""
    SELECT 
        p.id,
        p.sku,
        p.brand,
        p.model,
        p.title,
        p.base_price as price,
        pc1.platform_name as platform_a,
        pc2.platform_name as platform_b,
        CASE 
            WHEN pc1.platform_name = 'reverb' THEN rl_a.reverb_state
            WHEN pc1.platform_name = 'ebay' THEN el_a.listing_status
            WHEN pc1.platform_name = 'shopify' THEN sl_a.status
            WHEN pc1.platform_name = 'vr' THEN vl_a.vr_state
        END as status_a,
        CASE 
            WHEN pc2.platform_name = 'reverb' THEN rl_b.reverb_state
            WHEN pc2.platform_name = 'ebay' THEN el_b.listing_status
            WHEN pc2.platform_name = 'shopify' THEN sl_b.status
            WHEN pc2.platform_name = 'vr' THEN vl_b.vr_state
        END as status_b,
        psm_a.central_status as central_status_a,
        psm_b.central_status as central_status_b,
        p.primary_image
    FROM platform_common pc1
    INNER JOIN platform_common pc2 ON pc1.product_id = pc2.product_id
    INNER JOIN products p ON pc1.product_id = p.id
    LEFT JOIN reverb_listings rl_a ON (pc1.platform_name = 'reverb' AND CONCAT('REV-', pc1.external_id) = rl_a.reverb_listing_id)
    LEFT JOIN ebay_listings el_a ON (pc1.platform_name = 'ebay' AND pc1.external_id = el_a.ebay_item_id)
    LEFT JOIN shopify_listings sl_a ON (pc1.platform_name = 'shopify' AND pc1.id = sl_a.platform_id)
    LEFT JOIN vr_listings vl_a ON (pc1.platform_name = 'vr' AND pc1.external_id = vl_a.vr_listing_id)
    LEFT JOIN reverb_listings rl_b ON (pc2.platform_name = 'reverb' AND CONCAT('REV-', pc2.external_id) = rl_b.reverb_listing_id)
    LEFT JOIN ebay_listings el_b ON (pc2.platform_name = 'ebay' AND pc2.external_id = el_b.ebay_item_id)
    LEFT JOIN shopify_listings sl_b ON (pc2.platform_name = 'shopify' AND pc2.id = sl_b.platform_id)
    LEFT JOIN vr_listings vl_b ON (pc2.platform_name = 'vr' AND pc2.external_id = vl_b.vr_listing_id)
    LEFT JOIN platform_status_mappings psm_a ON (
        (pc1.platform_name = 'reverb' AND psm_a.platform_name = 'reverb' AND psm_a.platform_status = rl_a.reverb_state) OR
        (pc1.platform_name = 'ebay' AND psm_a.platform_name = 'ebay' AND psm_a.platform_status = el_a.listing_status) OR
        (pc1.platform_name = 'shopify' AND psm_a.platform_name = 'shopify' AND psm_a.platform_status = sl_a.status) OR
        (pc1.platform_name = 'vr' AND psm_a.platform_name = 'vr' AND psm_a.platform_status = vl_a.vr_state)
    )
    LEFT JOIN platform_status_mappings psm_b ON (
        (pc2.platform_name = 'reverb' AND psm_b.platform_name = 'reverb' AND psm_b.platform_status = rl_b.reverb_state) OR
        (pc2.platform_name = 'ebay' AND psm_b.platform_name = 'ebay' AND psm_b.platform_status = el_b.listing_status) OR
        (pc2.platform_name = 'shopify' AND psm_b.platform_name = 'shopify' AND psm_b.platform_status = sl_b.status) OR
        (pc2.platform_name = 'vr' AND psm_b.platform_name = 'vr' AND psm_b.platform_status = vl_b.vr_state)
    )
    WHERE pc1.platform_name = :platform_a 
    AND pc2.platform_name = :platform_b
    AND psm_a.central_status != psm_b.central_status
    ORDER BY p.base_price DESC;
    """)
    
    result = await db.execute(query, {"platform_a": platform_a, "platform_b": platform_b})
    return [dict(row._mapping) for row in result.fetchall()]


@router.get("/non-performing-inventory", response_class=HTMLResponse)
async def non_performing_inventory_report(
    request: Request,
    age_filter: Optional[str] = Query("3M"),
    sort_by: Optional[str] = Query("value"),
    sort_order: Optional[str] = Query("desc")
):
    """Non-performing inventory report with age filtering and sorting"""
    
    async with get_session() as db:
        try:
            # Summary metrics query with proper business filters
            summary_query = text("""
            WITH inventory_base AS (
                SELECT 
                    rl.reverb_listing_id,
                    p.sku,
                    p.brand,
                    p.model,
                    p.year,
                    p.base_price,
                    
                    -- Extract data - use table columns directly
                    rl.reverb_created_at as listing_date,
                    COALESCE((rl.extended_attributes->'buyer_price'->>'amount')::decimal, 0) as reverb_price,
                    COALESCE(rl.view_count, 0) as views,
                    COALESCE(rl.watch_count, 0) as watches,
                    COALESCE((rl.extended_attributes->>'offer_count')::int, 0) as offers,
                    
                    -- Calculate engagement metrics (NO DECIMALS)
                    ROUND(
                        COALESCE(rl.view_count::decimal, 0) / 
                        GREATEST(COALESCE(EXTRACT(days FROM (CURRENT_DATE - rl.reverb_created_at)), 30) / 30, 1), 0
                    ) as views_per_month,
                    
                    -- Red flags
                    CASE 
                        WHEN COALESCE(rl.view_count, 0) = 0 
                            AND COALESCE(rl.watch_count, 0) = 0 
                            AND COALESCE((rl.extended_attributes->>'offer_count')::int, 0) = 0 
                        THEN 'DEAD_STOCK'
                        WHEN COALESCE(rl.view_count, 0) > 50 
                            AND COALESCE((rl.extended_attributes->>'offer_count')::int, 0) = 0 
                        THEN 'HIGH_INTEREST_NO_OFFERS'
                        WHEN COALESCE((rl.extended_attributes->>'offer_count')::int, 0) > 3 
                        THEN 'MULTIPLE_OFFERS_UNSOLD'
                        ELSE 'NORMAL'
                    END as performance_flag,
                    
                    -- Platform coverage indicators
                    CASE WHEN EXISTS (
                        SELECT 1 FROM platform_common pc_shopify 
                        WHERE pc_shopify.product_id = p.id 
                        AND pc_shopify.platform_name = 'shopify'
                        AND pc_shopify.status NOT IN ('SOLD', 'ENDED')
                    ) THEN 1 ELSE 0 END as has_shopify,
                    
                    CASE WHEN EXISTS (
                        SELECT 1 FROM platform_common pc_ebay 
                        WHERE pc_ebay.product_id = p.id 
                        AND pc_ebay.platform_name = 'ebay'
                        AND pc_ebay.status NOT IN ('SOLD', 'ENDED')
                    ) THEN 1 ELSE 0 END as has_ebay,
                    
                    CASE WHEN EXISTS (
                        SELECT 1 FROM platform_common pc_vr 
                        WHERE pc_vr.product_id = p.id 
                        AND pc_vr.platform_name = 'vr'
                        AND pc_vr.status NOT IN ('SOLD', 'ENDED')
                    ) THEN 1 ELSE 0 END as has_vr

                FROM reverb_listings rl
                JOIN platform_common pc ON rl.reverb_listing_id = pc.external_id
                JOIN products p ON pc.product_id = p.id
                WHERE rl.reverb_state = 'live'
                AND rl.reverb_created_at IS NOT NULL
                AND pc.platform_name = 'reverb'
            )

            -- Summary with platform coverage counts
            SELECT 
                age_bucket,
                item_count,
                total_value,
                avg_price,
                avg_views,
                avg_watches,
                avg_offers,
                avg_views_per_month,
                dead_stock_count,
                high_interest_no_offers_count,
                multiple_offers_count,
                shopify_count,
                ebay_count,
                vr_count,
                sort_order
            FROM (
                SELECT 
                    'Older Than 3M' as age_bucket,
                    COUNT(*) as item_count,
                    SUM(reverb_price) as total_value,
                    ROUND(AVG(reverb_price), 0) as avg_price,
                    ROUND(AVG(views), 0) as avg_views,
                    ROUND(AVG(watches), 0) as avg_watches,
                    ROUND(AVG(offers), 0) as avg_offers,
                    ROUND(AVG(views_per_month), 0) as avg_views_per_month,
                    COUNT(*) FILTER (WHERE performance_flag = 'DEAD_STOCK') as dead_stock_count,
                    COUNT(*) FILTER (WHERE performance_flag = 'HIGH_INTEREST_NO_OFFERS') as high_interest_no_offers_count,
                    COUNT(*) FILTER (WHERE performance_flag = 'MULTIPLE_OFFERS_UNSOLD') as multiple_offers_count,
                    SUM(has_shopify) as shopify_count,
                    SUM(has_ebay) as ebay_count,
                    SUM(has_vr) as vr_count,
                    4 as sort_order
                FROM inventory_base 
                WHERE listing_date < (CURRENT_DATE - INTERVAL '3 months')

                UNION ALL

                SELECT 
                    'Older Than 6M' as age_bucket,
                    COUNT(*) as item_count,
                    SUM(reverb_price) as total_value,
                    ROUND(AVG(reverb_price), 0) as avg_price,
                    ROUND(AVG(views), 0) as avg_views,
                    ROUND(AVG(watches), 0) as avg_watches,
                    ROUND(AVG(offers), 0) as avg_offers,
                    ROUND(AVG(views_per_month), 0) as avg_views_per_month,
                    COUNT(*) FILTER (WHERE performance_flag = 'DEAD_STOCK') as dead_stock_count,
                    COUNT(*) FILTER (WHERE performance_flag = 'HIGH_INTEREST_NO_OFFERS') as high_interest_no_offers_count,
                    COUNT(*) FILTER (WHERE performance_flag = 'MULTIPLE_OFFERS_UNSOLD') as multiple_offers_count,
                    SUM(has_shopify) as shopify_count,
                    SUM(has_ebay) as ebay_count,
                    SUM(has_vr) as vr_count,
                    3 as sort_order
                FROM inventory_base 
                WHERE listing_date < (CURRENT_DATE - INTERVAL '6 months')

                UNION ALL

                SELECT 
                    'Older Than 12M' as age_bucket,
                    COUNT(*) as item_count,
                    SUM(reverb_price) as total_value,
                    ROUND(AVG(reverb_price), 0) as avg_price,
                    ROUND(AVG(views), 0) as avg_views,
                    ROUND(AVG(watches), 0) as avg_watches,
                    ROUND(AVG(offers), 0) as avg_offers,
                    ROUND(AVG(views_per_month), 0) as avg_views_per_month,
                    COUNT(*) FILTER (WHERE performance_flag = 'DEAD_STOCK') as dead_stock_count,
                    COUNT(*) FILTER (WHERE performance_flag = 'HIGH_INTEREST_NO_OFFERS') as high_interest_no_offers_count,
                    COUNT(*) FILTER (WHERE performance_flag = 'MULTIPLE_OFFERS_UNSOLD') as multiple_offers_count,
                    SUM(has_shopify) as shopify_count,
                    SUM(has_ebay) as ebay_count,
                    SUM(has_vr) as vr_count,
                    2 as sort_order
                FROM inventory_base 
                WHERE listing_date < (CURRENT_DATE - INTERVAL '12 months')

                UNION ALL

                SELECT 
                    'Older Than 24M' as age_bucket,
                    COUNT(*) as item_count,
                    SUM(reverb_price) as total_value,
                    ROUND(AVG(reverb_price), 0) as avg_price,
                    ROUND(AVG(views), 0) as avg_views,
                    ROUND(AVG(watches), 0) as avg_watches,
                    ROUND(AVG(offers), 0) as avg_offers,
                    ROUND(AVG(views_per_month), 0) as avg_views_per_month,
                    COUNT(*) FILTER (WHERE performance_flag = 'DEAD_STOCK') as dead_stock_count,
                    COUNT(*) FILTER (WHERE performance_flag = 'HIGH_INTEREST_NO_OFFERS') as high_interest_no_offers_count,
                    COUNT(*) FILTER (WHERE performance_flag = 'MULTIPLE_OFFERS_UNSOLD') as multiple_offers_count,
                    SUM(has_shopify) as shopify_count,
                    SUM(has_ebay) as ebay_count,
                    SUM(has_vr) as vr_count,
                    1 as sort_order
                FROM inventory_base 
                WHERE listing_date < (CURRENT_DATE - INTERVAL '24 months')
            ) summary_data
            ORDER BY sort_order
            """)
            
            summary_result = await db.execute(summary_query)
            summary_stats = [dict(row._mapping) for row in summary_result.fetchall()]
            
            # Updated detailed query with same filters
            age_filter_mapping = {
                "3M": "3 months",
                "6M": "6 months", 
                "12M": "12 months",
                "24M": "24 months"
            }
            
            interval = age_filter_mapping.get(age_filter, "3 months")
            
            sort_column_mapping = {
                "value": "reverb_price",
                "age": "listing_date",
                "views": "views",
                "watches": "watches", 
                "offers": "offers",
                "views_per_month": "views_per_month"
            }
            
            sort_column = sort_column_mapping.get(sort_by, "reverb_price")
            order_direction = "DESC" if sort_order == "desc" else "ASC"
            
            detailed_query = text(f"""
            WITH inventory_base AS (
                SELECT 
                    rl.reverb_listing_id,
                    p.sku,
                    p.brand,
                    p.model,
                    p.year,
                    p.base_price,
                    p.primary_image,
                    p.id as product_id,
                    
                    -- Extract data - use table columns directly
                    rl.reverb_created_at as listing_date,
                    COALESCE((rl.extended_attributes->'buyer_price'->>'amount')::decimal, 0) as reverb_price,
                    COALESCE(rl.view_count, 0) as views,
                    COALESCE(rl.watch_count, 0) as watches,
                    COALESCE((rl.extended_attributes->>'offer_count')::int, 0) as offers,
                    1 as inventory_quantity,
                    
                    -- Calculate days on market using reverb_created_at
                    COALESCE(
                        EXTRACT(days FROM (CURRENT_DATE - rl.reverb_created_at)), 
                        0
                    ) as days_on_market,
                    
                    -- Calculate engagement metrics
                    ROUND(
                        COALESCE(rl.view_count::decimal, 0) / 
                        GREATEST(
                            COALESCE(EXTRACT(days FROM (CURRENT_DATE - rl.reverb_created_at)), 30) / 30, 
                            1
                        ), 
                        0
                    ) as views_per_month,
                    
                    -- Red flags
                    CASE 
                        WHEN COALESCE(rl.view_count, 0) = 0 
                            AND COALESCE(rl.watch_count, 0) = 0 
                            AND COALESCE((rl.extended_attributes->>'offer_count')::int, 0) = 0 
                        THEN 'DEAD_STOCK'
                        WHEN COALESCE(rl.view_count, 0) > 50 
                            AND COALESCE((rl.extended_attributes->>'offer_count')::int, 0) = 0 
                        THEN 'HIGH_INTEREST_NO_OFFERS'
                        WHEN COALESCE((rl.extended_attributes->>'offer_count')::int, 0) > 3 
                        THEN 'MULTIPLE_OFFERS_UNSOLD'
                        ELSE 'NORMAL'
                    END as performance_flag,
                    
                    -- Platform coverage indicators
                    CASE WHEN pc_ebay.id IS NOT NULL THEN TRUE ELSE FALSE END as listed_on_ebay,
                    CASE WHEN pc_shopify.id IS NOT NULL THEN TRUE ELSE FALSE END as listed_on_shopify,
                    CASE WHEN pc_vr.id IS NOT NULL THEN TRUE ELSE FALSE END as listed_on_vr

                FROM reverb_listings rl
                JOIN platform_common pc ON rl.reverb_listing_id = pc.external_id
                JOIN products p ON pc.product_id = p.id
                
                -- LEFT JOIN to check other platform listings for the same product
                LEFT JOIN platform_common pc_ebay ON p.id = pc_ebay.product_id AND pc_ebay.platform_name = 'ebay'
                LEFT JOIN platform_common pc_shopify ON p.id = pc_shopify.product_id AND pc_shopify.platform_name = 'shopify'
                LEFT JOIN platform_common pc_vr ON p.id = pc_vr.product_id AND pc_vr.platform_name = 'vr'
                
                WHERE rl.reverb_state = 'live'
                AND rl.reverb_created_at IS NOT NULL
                AND pc.platform_name = 'reverb'
                AND rl.reverb_created_at < (CURRENT_DATE - INTERVAL '{interval}')
            )
            SELECT * FROM inventory_base
            ORDER BY {sort_column} {order_direction}
            LIMIT 400
            """)

            detailed_result = await db.execute(detailed_query)  # Remove the parameters
            detailed_items = [dict(row._mapping) for row in detailed_result.fetchall()]
            
            # Calculate total value for filtered items
            total_value = sum(float(item.get('reverb_price', 0) or 0) for item in detailed_items)
            
            logger.info(f"NPI Report: Found {len(summary_stats)} summary rows, {len(detailed_items)} detailed items (live only, single inventory)")
            
            return templates.TemplateResponse("reports/non_performing_inventory.html", {
                "request": request,
                "summary_stats": summary_stats,
                "detailed_items": detailed_items,
                "age_filter": age_filter,
                "sort_by": sort_by,
                "sort_order": sort_order,
                "total_value": total_value,
                "total_items": len(detailed_items),
                "age_filters": [
                    {"value": "3M", "label": "Older Than 3M"},
                    {"value": "6M", "label": "Older Than 6M"},
                    {"value": "12M", "label": "Older Than 12M"},
                    {"value": "24M", "label": "Older Than 24M"}
                ],
                "sort_options": [
                    {"value": "value", "label": "Value"},
                    {"value": "age", "label": "Age"},
                    {"value": "views", "label": "Views"},
                    {"value": "watches", "label": "Watches"},
                    {"value": "offers", "label": "Offers"},
                    {"value": "views_per_month", "label": "Views/Month"}
                ]
            })
            
        except Exception as e:
            logger.error(f"Error in non_performing_inventory_report: {e}")
            return templates.TemplateResponse("reports/non_performing_inventory.html", {
                "request": request,
                "error": f"Error generating report: {str(e)}",
                "summary_stats": [],
                "detailed_items": [],
                "age_filter": age_filter,
                "sort_by": sort_by,
                "sort_order": sort_order
            })


@router.get("/sync-events", response_class=HTMLResponse)
async def sync_events_report(
    request: Request,
    db: AsyncSession = Depends(get_session),
    platform_filter: Optional[str] = Query(None, alias="platform"),
    change_type_filter: Optional[str] = Query(None, alias="change_type"),
    status_filter: Optional[str] = Query("pending", alias="status"),
    sort_by: Optional[str] = Query("change_type", alias="sort"),
    sort_order: Optional[str] = Query("asc", alias="order")
):
    """
    Report for viewing and filtering unprocessed synchronization events.
    """
    async with get_session() as db:
        # --- 1. Fetch Status Counts ---
        status_counts_query = text("""
        SELECT status, COUNT(*) as count
        FROM sync_events
        GROUP BY status
        ORDER BY status;
        """)
        status_counts_result = await db.execute(status_counts_query)
        status_counts = {row.status: row.count for row in status_counts_result.fetchall()}

        # --- 2. Fetch Platform Counts ---
        platform_counts_query = text("""
        SELECT platform_name, COUNT(*) as count
        FROM sync_events
        GROUP BY platform_name
        ORDER BY platform_name;
        """)
        platform_counts_result = await db.execute(platform_counts_query)
        platform_counts = {row.platform_name: row.count for row in platform_counts_result.fetchall()}

        # --- 3. Fetch Change Type Counts ---
        change_type_counts_query = text("""
        SELECT change_type, COUNT(*) as count
        FROM sync_events
        GROUP BY change_type
        ORDER BY change_type;
        """)
        change_type_counts_result = await db.execute(change_type_counts_query)
        change_type_counts = {row.change_type: row.count for row in change_type_counts_result.fetchall()}

        # --- 3. Build and Fetch Detailed Events List ---
        params = {}
        where_clauses = []

        if platform_filter:
            where_clauses.append("se.platform_name = :platform")
            params["platform"] = platform_filter
        if change_type_filter:
            where_clauses.append("se.change_type = :change_type")
            params["change_type"] = change_type_filter
        if status_filter:
            where_clauses.append("se.status = :status")
            params["status"] = status_filter
            
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        # **NEW**: Whitelist sortable columns for security
        sortable_columns = {
            "event": "status",
            "change_type": "change_type",
            "product": "product_id",
            "detected_at": "detected_at",
            "status": "status"
        }
        sort_column = sortable_columns.get(sort_by, "detected_at")
        sort_direction = "ASC" if sort_order == "asc" else "DESC"

        detailed_query = text(f"""
        SELECT
            se.id,
            se.platform_name,
            se.product_id,
            se.external_id,
            se.change_type,
            se.change_data,
            se.status,
            se.detected_at,
            se.notes,
            p.primary_image,
            p.brand,
            p.model,
            p.sku as product_sku
        FROM sync_events se
        LEFT JOIN products p ON se.product_id = p.id
        WHERE {where_sql}
        ORDER BY {sort_column} {sort_direction}, id DESC
        LIMIT 500;
        """)

        detailed_result = await db.execute(detailed_query, params)
        sync_events = [dict(row._mapping) for row in detailed_result.fetchall()]

        for event in sync_events:
            change_data = event.get('change_data')
            if isinstance(change_data, str):
                try:
                    change_data = json.loads(change_data)
                except json.JSONDecodeError:
                    change_data = {}
            event['change_data'] = change_data or {}
            event['match_candidate'] = event['change_data'].get('match_candidate')
            event['suggested_action'] = event['change_data'].get('suggested_action')

    available_platforms = ["reverb", "ebay", "shopify", "vr"]
    available_change_types = [
        "new_listing", "price_change", "status_change", "removed_listing", "title", "description"
    ]

    return templates.TemplateResponse("reports/sync_events_report.html", {
        "request": request,
        "sync_events": sync_events,
        "status_counts": status_counts,
        "platform_counts": platform_counts,
        "change_type_counts": change_type_counts,
        "platform_filter": platform_filter,
        "change_type_filter": change_type_filter,
        "status_filter": status_filter,
        "sort_by": sort_by,
        "sort_order": sort_order,
        "platforms": available_platforms,
        "change_types": available_change_types
    })


@router.get("/platform-coverage", response_class=HTMLResponse)
async def platform_coverage_report(
    request: Request,
    status_filter: Optional[str] = Query("ACTIVE", description="Filter by product status"),
    sort_by: Optional[str] = Query("missing_count", description="Sort by column"),
    sort_order: Optional[str] = Query("desc", description="Sort order (asc/desc)")
):
    """
    Platform Coverage Report: Identify products missing from certain platforms.
    Enhanced with filtering by status and sortable columns.
    """
    async with get_session() as db:
        # Build WHERE clause for status filter
        status_clause = ""
        params = {}
        
        if status_filter and status_filter != "ALL":
            status_clause = "WHERE p.status = :status_filter"
            params["status_filter"] = status_filter
        elif status_filter != "ALL":
            # Default to ACTIVE if no filter specified
            status_clause = "WHERE p.status = 'ACTIVE'"
        
        # Map sort columns to SQL
        sort_column_map = {
            "sku": "sku",
            "brand": "brand",
            "model": "model",
            "base_price": "base_price",
            "missing_count": "missing_count",
            "platform_count": "platform_count"
        }
        
        # Validate sort column
        sort_col = sort_column_map.get(sort_by, "missing_count")
        sort_dir = "DESC" if sort_order == "desc" else "ASC"
        
        query = text(f"""
        WITH platform_coverage AS (
            SELECT 
                p.id AS product_id,
                p.sku,
                p.brand,
                p.model,
                p.base_price,
                p.status,
                COALESCE(ARRAY_AGG(pc.platform_name) FILTER (WHERE pc.platform_name IS NOT NULL), ARRAY[]::text[]) AS platforms
            FROM products p
            LEFT JOIN platform_common pc ON p.id = pc.product_id 
                AND (pc.status NOT IN ('SOLD', 'ENDED') OR pc.status IS NULL)
            {status_clause}
            GROUP BY p.id, p.sku, p.brand, p.model, p.base_price, p.status
        ),
        coverage_data AS (
            SELECT 
                product_id,
                sku,
                brand,
                model,
                base_price,
                status,
                platforms,
                CASE 
                    WHEN ARRAY_LENGTH(platforms, 1) IS NULL THEN 0 
                    ELSE ARRAY_LENGTH(platforms, 1) 
                END AS platform_count,
                ARRAY(
                    SELECT unnest(ARRAY['shopify', 'ebay', 'reverb', 'vr']) 
                    EXCEPT 
                    SELECT unnest(platforms)
                ) AS missing_platforms,
                CASE 
                    WHEN ARRAY_LENGTH(platforms, 1) IS NULL THEN 4
                    ELSE 4 - ARRAY_LENGTH(platforms, 1)
                END AS missing_count
            FROM platform_coverage
            WHERE ARRAY_LENGTH(platforms, 1) IS NULL OR ARRAY_LENGTH(platforms, 1) < 4
        )
        SELECT * FROM coverage_data
        ORDER BY {sort_col} {sort_dir}, 
                 ARRAY_TO_STRING(missing_platforms, ',') ASC,
                 sku ASC;
        """)
        
        result = await db.execute(query, params)
        coverage_data = [dict(row._mapping) for row in result.fetchall()]
        
        # Get available statuses for filter
        status_query = text("SELECT DISTINCT status FROM products WHERE status IS NOT NULL ORDER BY status")
        status_result = await db.execute(status_query)
        available_statuses = ["ALL"] + [row[0] for row in status_result.fetchall()]
        
        return templates.TemplateResponse("reports/platform_coverage.html", {
            "request": request,
            "coverage_data": coverage_data,
            "status_filter": status_filter,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "available_statuses": available_statuses
        })

@router.post("/sync-events/process/{event_id}")
async def process_sync_event(
    event_id: int,
    request: Request,
    settings: Settings = Depends(get_settings)
):
    """Process a single sync event - handles all event types including new listings."""
    try:
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}

        action = payload.get('action', 'process')
        product_identifier = payload.get('product_id') or payload.get('product_identifier') or payload.get('sku')

        async with get_session() as db:
            # Check the event type first
            stmt = select(SyncEvent).where(SyncEvent.id == event_id)
            result = await db.execute(stmt)
            event = result.scalar_one_or_none()

            if not event:
                return {
                    "status": "error",
                    "message": f"Sync event {event_id} not found"
                }

            if action == 'delete':
                return await _apply_manual_delete(db, event)

            if action == 'match':
                product = await _resolve_product_identifier(db, product_identifier)
                if not product:
                    return {
                        "status": "error",
                        "message": f"Unable to locate product '{product_identifier}'"
                    }

                change_data = event.change_data or {}
                change_data['manual_match'] = {
                    'product_id': product.id,
                    'identifier': product_identifier,
                }
                event.change_data = change_data
                event.product_id = product.id
                await db.commit()

            # Route based on event type
            if event.change_type == 'new_listing':
                # Use the EventProcessor class EXACTLY like the CLI script
                from app.services.event_processor import EventProcessor

                processor = EventProcessor(db, dry_run=False)
                result = await processor.process_sync_event(event)

                return {
                    "status": "success" if result.success else "error",
                    "message": result.message,
                    "details": {
                        "product_id": result.product_id,
                        "platforms_created": result.platforms_created,
                        "platforms_failed": result.platforms_failed,
                        "errors": result.errors
                    }
                }
            else:
                # Use the existing reconciliation service for other event types
                report = await process_reconciliation(
                    db=db,
                    event_id=event_id,
                    dry_run=False  # Always live mode from UI
                )

                # Format the response
                if report.summary['errors'] > 0:
                    return {
                        "status": "error",
                        "message": f"Processed with errors: {report.summary['errors']} errors",
                        "summary": report.summary,
                        "actions": report.actions_taken
                    }
                elif report.summary['processed'] == 0:
                    return {
                        "status": "warning",
                        "message": "No events were processed",
                        "summary": report.summary
                    }
                else:
                    return {
                        "status": "success",
                        "message": f"Successfully processed {report.summary['processed']} event(s)",
                        "summary": report.summary,
                        "actions": report.actions_taken
                    }
            
    except Exception as e:
        logger.error(f"Error processing sync event {event_id}: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


async def _resolve_product_identifier(db: AsyncSession, identifier: Optional[str]) -> Optional[Product]:
    if not identifier:
        return None

    identifier_str = str(identifier).strip()
    if not identifier_str:
        return None

    if identifier_str.isdigit():
        product = await db.get(Product, int(identifier_str))
        if product:
            return product

    stmt = select(Product).where(func.lower(Product.sku) == identifier_str.lower())
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _apply_manual_delete(db: AsyncSession, event: SyncEvent) -> Dict[str, Any]:
    product = None
    if event.product_id:
        product = await db.get(Product, event.product_id)

    if product:
        stmt = select(PlatformCommon).where(
            PlatformCommon.product_id == product.id,
            PlatformCommon.platform_name == event.platform_name,
        )
        platform_common = (await db.execute(stmt)).scalar_one_or_none()

        if platform_common:
            platform_common.status = ListingStatus.ENDED.value if hasattr(ListingStatus, 'ENDED') else 'ENDED'
            platform_common.sync_status = SyncStatus.SYNCED.value
            platform_common.last_sync = datetime.utcnow()
            platform_common.platform_specific_data = platform_common.platform_specific_data or {}

            if event.platform_name == 'ebay':
                stmt = select(EbayListing).where(EbayListing.platform_id == platform_common.id)
                listing = (await db.execute(stmt)).scalar_one_or_none()
                if listing:
                    listing.listing_status = 'ENDED'
                    listing.quantity_available = 0
                    listing.last_synced_at = datetime.utcnow()

            elif event.platform_name == 'shopify':
                stmt = select(ShopifyListing).where(ShopifyListing.platform_id == platform_common.id)
                listing = (await db.execute(stmt)).scalar_one_or_none()
                if listing:
                    listing.status = 'ARCHIVED'
                    listing.last_synced_at = datetime.utcnow()

            elif event.platform_name == 'vr':
                stmt = select(VRListing).where(VRListing.platform_id == platform_common.id)
                listing = (await db.execute(stmt)).scalar_one_or_none()
                if listing:
                    listing.vr_state = 'ended'
                    listing.last_synced_at = datetime.utcnow()

    event.status = 'processed'
    event.processed_at = datetime.utcnow()
    notes_payload = {
        'action': 'manual_delete',
        'timestamp': datetime.utcnow().isoformat(),
    }
    event.notes = json.dumps(notes_payload)

    await db.commit()

    return {
        'status': 'success',
        'message': 'Listing marked as deleted locally. Please ensure the platform listing is removed if necessary.'
    }


@router.get("/sync-stats", response_class=HTMLResponse)
async def sync_stats_report(
    request: Request,
    db: AsyncSession = Depends(get_session),
    platform_filter: Optional[str] = Query(None, alias="platform"),
    days_filter: Optional[int] = Query(30, alias="days")
):
    """
    Sync Statistics Report: View comprehensive sync performance metrics.
    """
    async with get_session() as db:
        from app.services.sync_stats_service import SyncStatsService
        from sqlalchemy import desc
        from app.models import SyncStats
        from datetime import datetime, timedelta
        
        stats_service = SyncStatsService(db)
        
        # Get cumulative stats
        cumulative_stats = await stats_service.get_current_stats(platform_filter)
        
        # Get recent sync runs
        cutoff_date = datetime.now() - timedelta(days=days_filter)
        
        stmt = text("""
            SELECT 
                created_at,
                sync_run_id,
                platform,
                run_events_processed,
                run_sales,
                run_listings_created,
                run_listings_updated,
                run_listings_removed,
                run_errors,
                run_duration_seconds,
                metadata_json
            FROM sync_stats
            WHERE sync_run_id IS NOT NULL
            AND created_at >= :cutoff_date
            ORDER BY created_at DESC
            LIMIT 100
        """)
        
        result = await db.execute(stmt, {"cutoff_date": cutoff_date})
        recent_runs = [dict(row._mapping) for row in result.fetchall()]
        
        # Get daily aggregates for chart
        daily_stats_query = text("""
            SELECT 
                DATE(created_at) as date,
                SUM(run_events_processed) as events,
                SUM(run_sales) as sales,
                SUM(run_listings_created) as created,
                SUM(run_errors) as errors
            FROM sync_stats
            WHERE sync_run_id IS NOT NULL
            AND created_at >= :cutoff_date
            GROUP BY DATE(created_at)
            ORDER BY date ASC
        """)
        
        daily_result = await db.execute(daily_stats_query, {"cutoff_date": cutoff_date})
        daily_stats = [dict(row._mapping) for row in daily_result.fetchall()]
        
        # Get platform breakdown
        platform_query = text("""
            SELECT 
                platform,
                COUNT(*) as sync_count,
                SUM(run_events_processed) as total_events,
                SUM(run_errors) as total_errors,
                AVG(run_duration_seconds) as avg_duration
            FROM sync_stats
            WHERE sync_run_id IS NOT NULL
            AND platform IS NOT NULL
            AND created_at >= :cutoff_date
            GROUP BY platform
            ORDER BY total_events DESC
        """)
        
        platform_result = await db.execute(platform_query, {"cutoff_date": cutoff_date})
        platform_breakdown = [dict(row._mapping) for row in platform_result.fetchall()]
        
        return templates.TemplateResponse("reports/sync_stats.html", {
            "request": request,
            "cumulative_stats": cumulative_stats,
            "recent_runs": recent_runs,
            "daily_stats": daily_stats,
            "platform_breakdown": platform_breakdown,
            "platform_filter": platform_filter,
            "days_filter": days_filter
        })


@router.get("/sales", response_class=HTMLResponse)
async def sales_report(
    request: Request,
    platform_filter: Optional[str] = Query(None, alias="platform"),
    days_filter: Optional[int] = Query(30, alias="days"),
    sort_by: Optional[str] = Query("sale_date", alias="sort"),
    sort_order: Optional[str] = Query("desc", alias="order")
):
    """
    Sales & Ended Listings Report: Track sold items and intelligently determine sale platforms.
    """
    async with get_session() as db:
        from datetime import datetime, timedelta
        
        # Calculate cutoff date
        cutoff_date = datetime.now() - timedelta(days=days_filter) if days_filter else None
        
        # Build WHERE clause
        where_clauses = []
        params = {}
        
        if cutoff_date:
            where_clauses.append("se.detected_at >= :cutoff_date")
            params["cutoff_date"] = cutoff_date
            
        if platform_filter:
            where_clauses.append("se.platform_name = :platform")
            params["platform"] = platform_filter
            
        where_sql = " AND " + " AND ".join(where_clauses) if where_clauses else ""
        
        # Map sort columns (these are used in the final SELECT, not in CTEs)
        sort_column_map = {
            "sale_date": "sale_date",
            "sku": "sku",
            "brand": "brand",
            "model": "model",
            "price": "base_price",
            "platform": "sale_platform"
        }
        
        sort_col = sort_column_map.get(sort_by, "sale_date")
        sort_dir = "DESC" if sort_order == "desc" else "ASC"
        
        # Query for sold/ended items with platform detection logic
        sales_query = text(f"""
            WITH ranked_sales AS (
                SELECT 
                    p.id as product_id,
                    p.sku,
                    p.brand,
                    p.model,
                    p.year,
                    p.base_price,
                    p.primary_image,
                    p.status,
                    se.platform_name as reporting_platform,
                    se.detected_at as sale_date,
                    se.change_data->>'new' as change_type,
                    ROW_NUMBER() OVER (
                        PARTITION BY p.id, DATE(se.detected_at) 
                        ORDER BY se.detected_at DESC
                    ) as rn
                FROM sync_events se
                JOIN products p ON se.product_id = p.id
                WHERE se.change_type = 'status_change'
                AND se.change_data->>'new' IN ('sold', 'ended')
                {" AND " + " AND ".join(where_clauses) if where_clauses else ""}
            ),
            sales_data AS (
                SELECT 
                    rs.*,
                    
                    -- Count active platforms at time of sale
                    (SELECT COUNT(DISTINCT pc2.platform_name) 
                     FROM platform_common pc2 
                     WHERE pc2.product_id = rs.product_id 
                     AND pc2.status IN ('ACTIVE', 'DRAFT')
                    ) as active_platform_count,
                    
                    -- Get all platforms that had this product
                    (SELECT ARRAY_AGG(DISTINCT pc.platform_name)
                     FROM platform_common pc
                     WHERE pc.product_id = rs.product_id
                    ) as all_platforms,
                    
                    -- Determine sale platform
                    CASE 
                        -- If only one platform had it active, it sold there
                        WHEN (SELECT COUNT(DISTINCT pc2.platform_name) 
                              FROM platform_common pc2 
                              WHERE pc2.product_id = rs.product_id 
                              AND pc2.status IN ('ACTIVE', 'DRAFT')
                             ) = 1 
                        THEN rs.reporting_platform
                        
                        -- If multiple platforms but only one reports sold, it sold there
                        WHEN (SELECT COUNT(DISTINCT se2.platform_name)
                              FROM sync_events se2
                              WHERE se2.product_id = rs.product_id
                              AND se2.change_type = 'status_change'
                              AND se2.change_data->>'new' IN ('sold', 'ended')
                             ) = 1
                        THEN rs.reporting_platform
                        
                        -- If all platforms report ended/sold, it was removed offline
                        WHEN (SELECT COUNT(DISTINCT pc2.platform_name) 
                              FROM platform_common pc2 
                              WHERE pc2.product_id = rs.product_id
                             ) = 
                             (SELECT COUNT(DISTINCT se2.platform_name)
                              FROM sync_events se2
                              WHERE se2.product_id = rs.product_id
                              AND se2.change_type = 'status_change'
                              AND se2.change_data->>'new' IN ('sold', 'ended')
                             )
                        THEN 'offline'
                        
                        -- Otherwise, use the reporting platform
                        ELSE rs.reporting_platform
                    END as sale_platform,
                    
                    -- Sale confidence score
                    CASE 
                        WHEN rs.change_type = 'sold' THEN 'confirmed'
                        WHEN rs.change_type = 'ended' THEN 'likely'
                        ELSE 'uncertain'
                    END as sale_confidence
                    
                FROM ranked_sales rs
                WHERE rs.rn = 1
            )
            SELECT * FROM sales_data
            ORDER BY {sort_col} {sort_dir}
            LIMIT 500
        """)
        
        sales_result = await db.execute(sales_query, params)
        sales_data = [dict(row._mapping) for row in sales_result.fetchall()]
        
        # Prepare summary statistics directly from the filtered sales data so
        # the headline figures always match the table rows the user sees.
        from decimal import Decimal
        from collections import Counter

        platform_totals = Counter()
        total_value = Decimal("0")

        for sale in sales_data:
            price = sale.get("base_price") or 0
            total_value += Decimal(str(price))

            platform_key = (sale.get("sale_platform") or sale.get("reporting_platform") or "").lower()
            if platform_key in {"reverb", "ebay", "shopify", "vr"}:
                platform_totals[platform_key] += 1

        total_sold = len(sales_data)
        avg_sale_price = (total_value / total_sold) if total_sold else Decimal("0")

        summary_stats = {
            "total_sold": total_sold,
            "total_value": float(total_value),
            "avg_sale_price": float(avg_sale_price),
            "reverb_sales": platform_totals.get("reverb", 0),
            "ebay_sales": platform_totals.get("ebay", 0),
            "shopify_sales": platform_totals.get("shopify", 0),
            "vr_sales": platform_totals.get("vr", 0),
        }

        # Build WHERE clause for the trend query using the same filters as the
        # table. (We only need this for the trend after the summary change.)
        summary_where_clauses = ["se.change_type = 'status_change'", "se.change_data->>'new' IN ('sold', 'ended')"]
        if cutoff_date:
            summary_where_clauses.append("se.detected_at >= :cutoff_date")
        if platform_filter:
            summary_where_clauses.append("se.platform_name = :platform")
        summary_where_sql = " WHERE " + " AND ".join(summary_where_clauses)

        # Get daily sales trend
        trend_query = text(f"""
            SELECT 
                DATE(se.detected_at) as sale_date,
                COUNT(DISTINCT p.id) as items_sold,
                SUM(p.base_price) as daily_revenue
            FROM sync_events se
            JOIN products p ON se.product_id = p.id
            {summary_where_sql}
            GROUP BY DATE(se.detected_at)
            ORDER BY sale_date DESC
            LIMIT 30
        """)
        
        trend_result = await db.execute(trend_query, params)
        sales_trend = [dict(row._mapping) for row in trend_result.fetchall()]
        
        return templates.TemplateResponse("reports/sales.html", {
            "request": request,
            "sales_data": sales_data,
            "summary_stats": summary_stats,
            "sales_trend": sales_trend,
            "platform_filter": platform_filter,
            "days_filter": days_filter,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "platforms": ["reverb", "ebay", "shopify", "vr"]
        })


@router.get("/sales/export/csv")
async def export_sales_csv(
    platform_filter: Optional[str] = Query(None, alias="platform"),
    days_filter: Optional[int] = Query(30, alias="days"),
    sort_by: Optional[str] = Query("sale_date", alias="sort"),
    sort_order: Optional[str] = Query("desc", alias="order")
):
    """
    Export sales report data as CSV.
    """
    import csv
    import io
    from fastapi.responses import StreamingResponse
    
    async with get_session() as db:
        from datetime import datetime, timedelta
        
        # Calculate cutoff date
        cutoff_date = datetime.now() - timedelta(days=days_filter) if days_filter else None
        
        # Build WHERE clause
        where_clauses = []
        params = {}
        
        if cutoff_date:
            where_clauses.append("se.detected_at >= :cutoff_date")
            params["cutoff_date"] = cutoff_date
            
        if platform_filter:
            where_clauses.append("se.platform_name = :platform")
            params["platform"] = platform_filter
            
        # Map sort columns (these are used in the final SELECT, not in CTEs)
        sort_column_map = {
            "sale_date": "sale_date",
            "sku": "sku",
            "brand": "brand",
            "model": "model",
            "price": "base_price",
            "platform": "sale_platform"
        }
        
        sort_col = sort_column_map.get(sort_by, "sale_date")
        sort_dir = "DESC" if sort_order == "desc" else "ASC"
        
        # Use the same query as the main sales report
        sales_query = text(f"""
            WITH ranked_sales AS (
                SELECT 
                    p.id as product_id,
                    p.sku,
                    p.brand,
                    p.model,
                    p.year,
                    p.base_price,
                    p.primary_image,
                    p.status,
                    se.platform_name as reporting_platform,
                    se.detected_at as sale_date,
                    se.change_data->>'new' as change_type,
                    ROW_NUMBER() OVER (
                        PARTITION BY p.id, DATE(se.detected_at) 
                        ORDER BY se.detected_at DESC
                    ) as rn
                FROM sync_events se
                JOIN products p ON se.product_id = p.id
                WHERE se.change_type = 'status_change'
                AND se.change_data->>'new' IN ('sold', 'ended')
                {" AND " + " AND ".join(where_clauses) if where_clauses else ""}
            ),
            sales_data AS (
                SELECT 
                    rs.*,
                    
                    -- Count active platforms at time of sale
                    (SELECT COUNT(DISTINCT pc2.platform_name) 
                     FROM platform_common pc2 
                     WHERE pc2.product_id = rs.product_id 
                     AND pc2.status IN ('ACTIVE', 'DRAFT')
                    ) as active_platform_count,
                    
                    -- Get all platforms that had this product
                    (SELECT ARRAY_AGG(DISTINCT pc.platform_name)
                     FROM platform_common pc
                     WHERE pc.product_id = rs.product_id
                    ) as all_platforms,
                    
                    -- Determine sale platform
                    CASE 
                        -- If only one platform had it active, it sold there
                        WHEN (SELECT COUNT(DISTINCT pc2.platform_name) 
                              FROM platform_common pc2 
                              WHERE pc2.product_id = rs.product_id 
                              AND pc2.status IN ('ACTIVE', 'DRAFT')
                             ) = 1 
                        THEN rs.reporting_platform
                        
                        -- If multiple platforms but only one reports sold, it sold there
                        WHEN (SELECT COUNT(DISTINCT se2.platform_name)
                              FROM sync_events se2
                              WHERE se2.product_id = rs.product_id
                              AND se2.change_type = 'status_change'
                              AND se2.change_data->>'new' IN ('sold', 'ended')
                             ) = 1
                        THEN rs.reporting_platform
                        
                        -- If all platforms report ended/sold, it was removed offline
                        WHEN (SELECT COUNT(DISTINCT pc2.platform_name) 
                              FROM platform_common pc2 
                              WHERE pc2.product_id = rs.product_id
                             ) = 
                             (SELECT COUNT(DISTINCT se2.platform_name)
                              FROM sync_events se2
                              WHERE se2.product_id = rs.product_id
                              AND se2.change_type = 'status_change'
                              AND se2.change_data->>'new' IN ('sold', 'ended')
                             )
                        THEN 'offline'
                        
                        -- Otherwise, use the reporting platform
                        ELSE rs.reporting_platform
                    END as sale_platform,
                    
                    -- Sale confidence score
                    CASE 
                        WHEN rs.change_type = 'sold' THEN 'confirmed'
                        WHEN rs.change_type = 'ended' THEN 'likely'
                        ELSE 'uncertain'
                    END as sale_confidence
                    
                FROM ranked_sales rs
                WHERE rs.rn = 1
            )
            SELECT * FROM sales_data
            ORDER BY {sort_col} {sort_dir}
        """)
        
        sales_result = await db.execute(sales_query, params)
        sales_data = [dict(row._mapping) for row in sales_result.fetchall()]
        
        # Create CSV
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write headers
        writer.writerow([
            'SKU', 'Brand', 'Model', 'Year', 'Price (£)', 'Sale Date', 
            'Reporting Platform', 'Sale Platform', 'Confidence', 'Status', 'All Platforms'
        ])
        
        # Write data
        for sale in sales_data:
            writer.writerow([
                sale['sku'],
                sale['brand'],
                sale['model'],
                sale['year'] or '',
                f"{sale['base_price']:.2f}",
                sale['sale_date'].strftime('%Y-%m-%d %H:%M'),
                sale['reporting_platform'].upper(),
                sale['sale_platform'].upper(),
                sale['sale_confidence'],
                sale['status'],
                ', '.join(sale['all_platforms']) if sale['all_platforms'] else ''
            ])
        
        output.seek(0)
        
        # Return CSV file
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode('utf-8')),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=sales_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"}
        )


@router.get("/sales/export/pdf") 
async def export_sales_pdf(
    platform_filter: Optional[str] = Query(None, alias="platform"),
    days_filter: Optional[int] = Query(30, alias="days")
):
    """
    Export sales report data as a simple PDF.
    For now, redirect to CSV export as PDF generation requires additional setup.
    """
    # TODO: Implement proper PDF export using reportlab or weasyprint
    # For now, redirect to CSV which can be opened in Excel and saved as PDF
    from fastapi.responses import RedirectResponse
    
    # Build query params for CSV export
    params = []
    if platform_filter:
        params.append(f"platform={platform_filter}")
    if days_filter:
        params.append(f"days={days_filter}")
    
    query_string = "&".join(params) if params else ""
    redirect_url = f"/reports/sales/export/csv?{query_string}" if query_string else "/reports/sales/export/csv"
    
    return RedirectResponse(url=redirect_url)


@router.get("/price-inconsistencies", response_class=HTMLResponse)
async def price_inconsistencies_report(
    request: Request,
    threshold: float = Query(10.0, description="Price difference threshold percentage"),
    status_filter: Optional[str] = Query("ACTIVE", description="Filter by product status"),
    sort_by: Optional[str] = Query("max_diff", description="Sort by column"),
    sort_order: Optional[str] = Query("desc", description="Sort order (asc/desc)")
):
    """
    Price Inconsistencies Report: Detect products with significant price differences across platforms.
    """
    async with get_session() as db:
        # Build WHERE clause for status filter
        status_clause = ""
        params = {"threshold": threshold}
        
        if status_filter and status_filter != "ALL":
            status_clause = "WHERE p.status = :status_filter"
            params["status_filter"] = status_filter
        elif status_filter != "ALL":
            # Default to ACTIVE if no filter specified
            status_clause = "WHERE p.status = 'ACTIVE'"
        
        # Map sort columns
        sort_column_map = {
            "sku": "p.sku",
            "brand": "p.brand",
            "model": "p.model",
            "base_price": "p.base_price",
            "max_diff": "max_price_diff_pct",
            "platforms": "platform_count"
        }
        
        sort_col = sort_column_map.get(sort_by, "max_price_diff_pct")
        sort_dir = "DESC" if sort_order == "desc" else "ASC"
        
        # Query to find price inconsistencies
        query = text(f"""
            WITH platform_prices AS (
                SELECT 
                    p.id,
                    p.sku,
                    p.brand,
                    p.model,
                    p.year,
                    p.base_price,
                    p.primary_image,
                    p.status,
                    pc.platform_name,
                    pc.status as platform_status,
                    CASE 
                        WHEN pc.platform_name = 'reverb' THEN 
                            COALESCE((rl.extended_attributes->>'price')::float, rl.list_price, p.base_price)
                        WHEN pc.platform_name = 'ebay' THEN 
                            COALESCE(el.price, p.base_price)
                        WHEN pc.platform_name = 'shopify' THEN 
                            COALESCE((sl.extended_attributes->>'price')::float, p.base_price)
                        WHEN pc.platform_name = 'vr' THEN 
                            COALESCE(vl.price_notax, p.base_price)
                        ELSE p.base_price
                    END as platform_price
                FROM products p
                JOIN platform_common pc ON p.id = pc.product_id
                LEFT JOIN reverb_listings rl ON pc.id = rl.platform_id AND pc.platform_name = 'reverb'
                LEFT JOIN ebay_listings el ON pc.id = el.platform_id AND pc.platform_name = 'ebay'
                LEFT JOIN shopify_listings sl ON pc.id = sl.platform_id AND pc.platform_name = 'shopify'
                LEFT JOIN vr_listings vl ON pc.id = vl.platform_id AND pc.platform_name = 'vr'
                {status_clause}
                {"AND" if status_clause else "WHERE"} pc.status IN ('ACTIVE', 'DRAFT')
            ),
            price_analysis AS (
                SELECT 
                    id,
                    sku,
                    brand,
                    model,
                    year,
                    base_price,
                    primary_image,
                    status,
                    COUNT(DISTINCT platform_name) as platform_count,
                    MIN(platform_price) as min_price,
                    MAX(platform_price) as max_price,
                    AVG(platform_price) as avg_price,
                    MAX(platform_price) - MIN(platform_price) as price_diff,
                    CASE 
                        WHEN MIN(platform_price) > 0 THEN 
                            ((MAX(platform_price) - MIN(platform_price)) / MIN(platform_price) * 100)
                        ELSE 0
                    END as max_price_diff_pct,
                    ARRAY_AGG(
                        json_build_object(
                            'platform', platform_name,
                            'price', platform_price,
                            'status', platform_status
                        ) ORDER BY platform_price DESC
                    ) as platform_details
                FROM platform_prices
                GROUP BY id, sku, brand, model, year, base_price, primary_image, status
                HAVING COUNT(DISTINCT platform_name) > 1
                AND MAX(platform_price) > MIN(platform_price)
            )
            SELECT * FROM price_analysis
            WHERE max_price_diff_pct >= :threshold
            ORDER BY {sort_col} {sort_dir}
            LIMIT 500
        """)
        
        result = await db.execute(query, params)
        inconsistencies = [dict(row._mapping) for row in result.fetchall()]
        
        # Get summary statistics
        summary_query = text(f"""
            WITH platform_prices AS (
                SELECT 
                    p.id,
                    pc.platform_name,
                    CASE 
                        WHEN pc.platform_name = 'reverb' THEN 
                            COALESCE((rl.extended_attributes->>'price')::float, rl.list_price, p.base_price)
                        WHEN pc.platform_name = 'ebay' THEN 
                            COALESCE(el.price, p.base_price)
                        WHEN pc.platform_name = 'shopify' THEN 
                            COALESCE((sl.extended_attributes->>'price')::float, p.base_price)
                        WHEN pc.platform_name = 'vr' THEN 
                            COALESCE(vl.price_notax, p.base_price)
                        ELSE p.base_price
                    END as platform_price
                FROM products p
                JOIN platform_common pc ON p.id = pc.product_id
                LEFT JOIN reverb_listings rl ON pc.id = rl.platform_id AND pc.platform_name = 'reverb'
                LEFT JOIN ebay_listings el ON pc.id = el.platform_id AND pc.platform_name = 'ebay'
                LEFT JOIN shopify_listings sl ON pc.id = sl.platform_id AND pc.platform_name = 'shopify'
                LEFT JOIN vr_listings vl ON pc.id = vl.platform_id AND pc.platform_name = 'vr'
                {status_clause}
                {"AND" if status_clause else "WHERE"} pc.status IN ('ACTIVE', 'DRAFT')
            ),
            price_stats AS (
                SELECT 
                    id,
                    COUNT(DISTINCT platform_name) as platform_count,
                    MAX(platform_price) - MIN(platform_price) as price_diff,
                    CASE 
                        WHEN MIN(platform_price) > 0 THEN 
                            ((MAX(platform_price) - MIN(platform_price)) / MIN(platform_price) * 100)
                        ELSE 0
                    END as price_diff_pct
                FROM platform_prices
                GROUP BY id
                HAVING COUNT(DISTINCT platform_name) > 1
                AND MAX(platform_price) > MIN(platform_price)
            )
            SELECT 
                COUNT(DISTINCT id) as total_products,
                COUNT(DISTINCT CASE WHEN price_diff_pct >= :threshold THEN id END) as products_above_threshold,
                AVG(price_diff_pct) as avg_price_diff_pct,
                MAX(price_diff_pct) as max_price_diff_pct,
                SUM(price_diff) as total_price_variance
            FROM price_stats
        """)
        
        summary_result = await db.execute(summary_query, params)
        summary_stats = dict(summary_result.fetchone()._mapping)
        
        return templates.TemplateResponse("reports/price_inconsistencies.html", {
            "request": request,
            "inconsistencies": inconsistencies,
            "summary_stats": summary_stats,
            "threshold": threshold,
            "status_filter": status_filter,
            "sort_by": sort_by,
            "sort_order": sort_order
        })


@router.get("/matching", response_class=HTMLResponse)
async def matching_interface(request: Request):
    """Manual product matching interface"""
    return templates.TemplateResponse("matching/interface.html", {
        "request": request,
        "platforms": ["reverb", "shopify", "vr", "ebay"]
    })


# Matching API endpoints
from fastapi import Form
from fastapi.responses import JSONResponse


@router.get("/matching/api/stats")
async def get_matching_stats():
    """Get statistics for matching interface"""
    try:
        async with get_session() as db:
            query = text("""
                SELECT pc.platform_name, COUNT(*) as count
                FROM products p
                JOIN platform_common pc ON p.id = pc.product_id
                WHERE p.status = 'ACTIVE'
                GROUP BY pc.platform_name
                ORDER BY count DESC
            """)

            result = await db.execute(query)
            rows = result.fetchall()

            stats = {row.platform_name: row.count for row in rows}

            return JSONResponse(stats)

    except Exception as e:
        logger.error(f"Error getting stats: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/matching/api/match-stats")
async def get_match_stats():
    """Get detailed matching statistics for each platform"""
    try:
        async with get_session() as db:
            query = text("""
            WITH platform_totals AS (
                SELECT pc.platform_name, COUNT(*) as total_products
                FROM products p
                JOIN platform_common pc ON p.id = pc.product_id
                GROUP BY pc.platform_name
            ),
            all_matched AS (
                -- Combine all types of matching without double-counting
                SELECT pc.platform_name, COUNT(DISTINCT p.id) as matched_count
                FROM products p
                JOIN platform_common pc ON p.id = pc.product_id
                WHERE p.id IN (
                    -- Multi-platform products
                    SELECT product_id
                    FROM platform_common
                    GROUP BY product_id
                    HAVING COUNT(DISTINCT platform_name) > 1
                )
                OR p.id IN (
                    -- Manually matched products
                    SELECT DISTINCT kept_product_id FROM product_merges WHERE merged_at IS NOT NULL
                    UNION
                    SELECT DISTINCT merged_product_id FROM product_merges WHERE merged_at IS NOT NULL
                )
                GROUP BY pc.platform_name
            )
            SELECT
                pt.platform_name,
                pt.total_products,
                COALESCE(am.matched_count, 0) as matched_products,
                pt.total_products - COALESCE(am.matched_count, 0) as unmatched_products,
                ROUND(COALESCE(am.matched_count, 0) * 100.0 / NULLIF(pt.total_products, 0), 1) as match_percentage
            FROM platform_totals pt
            LEFT JOIN all_matched am ON pt.platform_name = am.platform_name
            ORDER BY pt.platform_name
            """)

            result = await db.execute(query)
            rows = result.fetchall()

            stats = {}
            for row in rows:
                stats[row.platform_name] = {
                    'total': int(row.total_products or 0),
                    'matched': int(row.matched_products or 0),
                    'unmatched': int(row.unmatched_products or 0),
                    'percentage': float(row.match_percentage or 0.0)
                }

            return JSONResponse(stats)

    except Exception as e:
        logger.error(f"Error getting match stats: {str(e)}")
        return JSONResponse({
            "reverb": {"total": 0, "matched": 0, "unmatched": 0, "percentage": 0.0},
            "shopify": {"total": 0, "matched": 0, "unmatched": 0, "percentage": 0.0},
            "vr": {"total": 0, "matched": 0, "unmatched": 0, "percentage": 0.0}
        })


@router.post("/matching/api/products")
async def get_products(
    platform: str = Form(...),
    brand: Optional[str] = Form(None),
    year: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    match_status: Optional[str] = Form(None),
    other_platform: Optional[str] = Form(None),
    price_min: Optional[float] = Form(None),
    price_max: Optional[float] = Form(None),
    search_text: Optional[str] = Form(None),
    offset: int = Form(0),
    limit: int = Form(30)
):
    """Get filtered products for matching interface"""
    try:
        async with get_session() as db:
            where_conditions = ["pc.platform_name = :platform"]
            params = {"platform": platform}

            if match_status == "unmatched":
                if other_platform and set([platform, other_platform]) == set(['reverb', 'shopify']):
                    where_conditions.append("1 = 0")
                else:
                    where_conditions.append("""
                        p.id NOT IN (
                            SELECT DISTINCT kept_product_id FROM product_merges WHERE merged_at IS NOT NULL
                            UNION
                            SELECT DISTINCT merged_product_id FROM product_merges WHERE merged_at IS NOT NULL
                        )
                    """)

            elif match_status == "matched":
                if other_platform and set([platform, other_platform]) == set(['reverb', 'shopify']):
                    pass
                else:
                    where_conditions.append("""
                        (p.id IN (SELECT DISTINCT kept_product_id FROM product_merges WHERE merged_at IS NOT NULL)
                        OR p.id IN (SELECT DISTINCT merged_product_id FROM product_merges WHERE merged_at IS NOT NULL))
                    """)

            if brand and brand.strip() and brand != "all":
                where_conditions.append("p.brand = :brand")
                params["brand"] = brand.strip()

            if year and year.strip() and year != "all":
                where_conditions.append("p.year = :year")
                params["year"] = int(year.strip())

            if status and status.strip() and status != "all":
                if platform == "vr":
                    where_conditions.append("pc.id IN (SELECT platform_id FROM vr_listings WHERE vr_state = :status)")
                elif platform == "reverb":
                    where_conditions.append("pc.id IN (SELECT platform_id FROM reverb_listings WHERE reverb_state = :status)")
                elif platform == "ebay":
                    where_conditions.append("pc.id IN (SELECT platform_id FROM ebay_listings WHERE listing_status = :status)")
                elif platform == "shopify":
                    where_conditions.append("pc.id IN (SELECT platform_id FROM shopify_listings WHERE status = :status)")

                params["status"] = status.strip()

            if price_min is not None:
                where_conditions.append("COALESCE(el.price, rl.price, vl.price, sl.price, p.base_price) >= :price_min")
                params["price_min"] = price_min

            if price_max is not None:
                where_conditions.append("COALESCE(el.price, rl.price, vl.price, sl.price, p.base_price) <= :price_max")
                params["price_max"] = price_max

            if search_text and search_text.strip():
                search_term = f"%{search_text.strip()}%"
                where_conditions.append("""
                    (LOWER(p.title) LIKE LOWER(:search_text) OR
                     LOWER(p.description) LIKE LOWER(:search_text) OR
                     LOWER(p.model) LIKE LOWER(:search_text) OR
                     LOWER(p.sku) LIKE LOWER(:search_text) OR
                     LOWER(p.finish) LIKE LOWER(:search_text))
                """)
                params["search_text"] = search_term

            where_clause = " AND ".join(where_conditions)

            query = text(f"""
            WITH ebay_prices AS (
                SELECT pc.id as platform_common_id, el.price, el.listing_status
                FROM platform_common pc
                JOIN ebay_listings el ON pc.external_id = el.ebay_item_id
                WHERE pc.platform_name = 'ebay'
            ),
            reverb_prices AS (
                SELECT pc.id as platform_common_id, rl.list_price as price, rl.reverb_state
                FROM platform_common pc
                JOIN reverb_listings rl ON CONCAT('REV-', pc.external_id) = rl.reverb_listing_id
                WHERE pc.platform_name = 'reverb'
            ),
            vintageandrare_prices AS (
                SELECT pc.id as platform_common_id, vl.price_notax as price, vl.vr_state
                FROM platform_common pc
                JOIN vr_listings vl ON pc.external_id = vl.vr_listing_id
                WHERE pc.platform_name = 'vintageandrare'
            ),
            shopify_prices AS (
                SELECT pc.id as platform_common_id, sl.price, sl.status
                FROM platform_common pc
                JOIN shopify_listings sl ON pc.id = sl.platform_id
                WHERE pc.platform_name = 'shopify'
            ),
            platform_urls AS (
                SELECT pc.id as platform_common_id,
                    CASE pc.platform_name
                        WHEN 'ebay' THEN 'https://www.ebay.co.uk/itm/' || pc.external_id
                        WHEN 'reverb' THEN 'https://reverb.com/item/' || pc.external_id
                        WHEN 'vr' THEN 'https://www.vintageandrare.com/product/' || pc.external_id
                        WHEN 'vintageandrare' THEN 'https://www.vintageandrare.com/product/' || pc.external_id
                        WHEN 'shopify' THEN 'https://your-shop.myshopify.com/products/' || sl.handle
                        ELSE NULL
                    END as platform_url
                FROM platform_common pc
                LEFT JOIN shopify_listings sl ON pc.id = sl.platform_id AND pc.platform_name = 'shopify'
            )
            SELECT
                p.id, p.sku, p.brand, p.model, p.title, p.year, p.description, p.base_price,
                p.category, p.condition, p.finish, p.status, p.created_at, p.primary_image,
                pc.platform_name, pc.id as platform_common_id, pc.external_id,
                COALESCE(ep.price, rp.price, vp.price, sp.price, p.base_price) as actual_price,
                COALESCE(ep.listing_status, rp.reverb_state, vp.vr_state, sp.status) as platform_status,
                pu.platform_url
            FROM products p
            JOIN platform_common pc ON p.id = pc.product_id
            LEFT JOIN ebay_prices ep ON pc.id = ep.platform_common_id
            LEFT JOIN reverb_prices rp ON pc.id = rp.platform_common_id
            LEFT JOIN vintageandrare_prices vp ON pc.id = vp.platform_common_id
            LEFT JOIN shopify_prices sp ON pc.id = sp.platform_common_id
            LEFT JOIN platform_urls pu ON pc.id = pu.platform_common_id
            WHERE {where_clause}
            ORDER BY COALESCE(ep.price, rp.price, vp.price, sp.price, p.base_price) DESC
            LIMIT :limit OFFSET :offset
            """)

            params.update({"limit": limit, "offset": offset})
            result = await db.execute(query, params)
            rows = result.mappings().fetchall()

            products = []
            for row in rows:
                product = {
                    "id": row["id"],
                    "sku": row["sku"],
                    "brand": row["brand"],
                    "model": row["model"],
                    "title": row["title"],
                    "year": row["year"],
                    "description": row["description"][:200] + "..." if row["description"] and len(row["description"]) > 200 else row["description"],
                    "category": row["category"],
                    "condition": row["condition"],
                    "finish": row["finish"],
                    "status": row["platform_status"] or row["status"],
                    "price": float(row["actual_price"]) if row["actual_price"] else None,
                    "base_price": float(row["base_price"]) if row["base_price"] else None,
                    "platform": row["platform_name"],
                    "platform_common_id": row["platform_common_id"],
                    "external_id": row["external_id"],
                    "platform_url": row["platform_url"],
                    "primary_image": row["primary_image"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None
                }
                products.append(product)

            return JSONResponse({
                "products": products,
                "count": len(products),
                "offset": offset,
                "limit": limit,
                "has_more": len(products) == limit
            })

    except Exception as e:
        logger.error(f"Error getting products: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/matching/api/confirm")
async def confirm_match(
    product1_id: int = Form(...),
    product2_id: int = Form(...)
):
    """Confirm a manual match between two products"""
    try:
        async with get_session() as db:
            query = text("""
                SELECT p.*, pc.platform_name, pc.id as platform_common_id
                FROM products p
                JOIN platform_common pc ON p.id = pc.product_id
                WHERE p.id = :product_id
            """)

            result1 = await db.execute(query, {"product_id": product1_id})
            product1_row = result1.mappings().fetchone()

            result2 = await db.execute(query, {"product_id": product2_id})
            product2_row = result2.mappings().fetchone()

            if not product1_row or not product2_row:
                return JSONResponse({
                    "success": False,
                    "message": "One or both products not found"
                })

            platform1 = product1_row['platform_name']
            platform2 = product2_row['platform_name']

            match = {
                f"{platform1}_product": dict(product1_row),
                f"{platform2}_product": dict(product2_row),
                "confidence": 100.0
            }

            matcher = ProductMatcher(db)
            merged_count = await matcher.merge_products([match], merged_by="manual_matching_interface")

            if merged_count > 0:
                return JSONResponse({
                    "success": True,
                    "message": f"Successfully merged {platform1} product {product1_row['sku']} with {platform2} product {product2_row['sku']}"
                })
            else:
                return JSONResponse({
                    "success": False,
                    "message": "Failed to merge products"
                })

    except Exception as e:
        logger.error(f"Error confirming match: {str(e)}")
        return JSONResponse({
            "success": False,
            "message": str(e)
        })


@router.get("/matching/api/history")
async def get_match_history(limit: int = 10):
    """Get recent match history"""
    try:
        async with get_session() as db:
            query = text("""
                SELECT
                    pm.kept_product_id,
                    pm.merged_product_id,
                    pm.merged_at,
                    pm.merged_by,
                    p_kept.sku as kept_sku,
                    p_kept.title as kept_title,
                    pc_kept.platform_name as kept_platform,
                    pm.merged_product_data->>'sku' as merged_sku,
                    pm.merged_product_data->>'title' as merged_title,
                    'merged' as merged_platform
                FROM product_merges pm
                LEFT JOIN products p_kept ON pm.kept_product_id = p_kept.id
                LEFT JOIN platform_common pc_kept ON pm.kept_product_id = pc_kept.product_id
                WHERE pm.merged_by LIKE '%manual%' OR pm.merged_by = 'manual_matching_interface'
                ORDER BY pm.merged_at DESC
                LIMIT :limit
            """)

            result = await db.execute(query, {'limit': limit})
            rows = result.fetchall()

            history = []
            for row in rows:
                history.append({
                    'platform1': row.kept_platform or 'unknown',
                    'product1_sku': row.kept_sku or 'unknown',
                    'platform2': 'merged',
                    'product2_sku': row.merged_sku or 'unknown',
                    'created_at': row.merged_at.isoformat() if row.merged_at else None
                })

            return JSONResponse(history)

    except Exception as e:
        logger.error(f"Error getting match history: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/matching/api/filter-options")
async def get_filter_options():
    """Get all available filter options (brands, years, price ranges)"""
    try:
        async with get_session() as db:
            brands_query = text("""
                SELECT DISTINCT p.brand
                FROM products p
                JOIN platform_common pc ON p.id = pc.product_id
                WHERE p.status = 'ACTIVE' AND p.brand IS NOT NULL AND p.brand != ''
                ORDER BY p.brand
            """)
            brands_result = await db.execute(brands_query)
            brands = [row.brand for row in brands_result.fetchall()]

            years_query = text("""
                SELECT DISTINCT p.year
                FROM products p
                JOIN platform_common pc ON p.id = pc.product_id
                WHERE p.status = 'ACTIVE' AND p.year IS NOT NULL
                ORDER BY p.year DESC
            """)
            years_result = await db.execute(years_query)
            years = [row.year for row in years_result.fetchall()]

            price_query = text("""
                SELECT
                    MIN(p.base_price) as min_price,
                    MAX(p.base_price) as max_price,
                    ARRAY_AGG(DISTINCT p.base_price ORDER BY p.base_price ASC) as all_prices
                FROM products p
                JOIN platform_common pc ON p.id = pc.product_id
                WHERE p.status = 'ACTIVE' AND p.base_price IS NOT NULL AND p.base_price > 0
            """)
            price_result = await db.execute(price_query)
            price_row = price_result.fetchone()

            if price_row and price_row.min_price:
                min_price = float(price_row.min_price)
                max_price = float(price_row.max_price)
                all_prices = [float(p) for p in price_row.all_prices[:50]]
            else:
                min_price, max_price = 100.0, 50000.0
                all_prices = [100, 500, 1000, 2000, 5000, 10000, 20000, 50000]

            return JSONResponse({
                "brands": brands,
                "years": years,
                "prices_asc": sorted(all_prices),
                "prices_desc": sorted(all_prices, reverse=True),
                "priceRange": {
                    "min": min_price,
                    "max": max_price
                }
            })

    except Exception as e:
        logger.error(f"Error getting filter options: {str(e)}")
        return JSONResponse({
            "brands": [],
            "years": [],
            "prices_asc": [100, 500, 1000, 5000, 10000],
            "prices_desc": [50000, 10000, 5000, 1000, 500, 100],
            "priceRange": {"min": 100, "max": 50000}
        })


@router.get("/matching/api/platform-status-options/{platform}")
async def get_platform_status_options(platform: str):
    """Get available status options for a specific platform"""
    try:
        async with get_session() as db:
            if platform == "reverb":
                query = text("SELECT DISTINCT reverb_state as status FROM reverb_listings WHERE reverb_state IS NOT NULL ORDER BY reverb_state")
            elif platform == "vr":
                query = text("SELECT DISTINCT vr_state as status FROM vr_listings WHERE vr_state IS NOT NULL ORDER BY vr_state")
            elif platform == "shopify":
                query = text("SELECT DISTINCT status FROM shopify_listings WHERE status IS NOT NULL ORDER BY status")
            elif platform == "ebay":
                query = text("SELECT DISTINCT listing_status as status FROM ebay_listings WHERE listing_status IS NOT NULL ORDER BY listing_status")
            else:
                return JSONResponse([])

            result = await db.execute(query)
            statuses = [row.status for row in result.fetchall()]

            return JSONResponse(statuses)

    except Exception as e:
        logger.error(f"Error getting platform status options: {str(e)}")
        return JSONResponse([])
