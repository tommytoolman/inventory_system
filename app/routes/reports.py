from fastapi import APIRouter, Request, Depends, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select, func, or_
from sqlalchemy.orm import selectinload
import json
from typing import Optional, List, Dict, Any
from datetime import datetime
from collections import Counter
from app.database import get_session
from app.core.templates import templates
from app.core.config import Settings, get_settings
from app.services.reconciliation_service import process_reconciliation
from app.services.ebay_service import EbayService
from app.models import SyncEvent
from app.models.product import Product, ProductStatus
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.models.ebay import EbayListing
from app.models.shopify import ShopifyListing
from app.models.vr import VRListing
from app.models.reverb import ReverbListing
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


@router.get("/crazylister-coverage", response_class=HTMLResponse)
async def crazylister_coverage_report(
    request: Request,
    status: str = Query("all", description="Filter by template status"),
    search: Optional[str] = Query(None, description="Search by SKU, brand, or title"),
    product_status: str = Query("active", description="Filter by product status"),
):
    """Show which eBay listings have the CrazyLister template applied."""

    valid_statuses = {"all", "applied", "missing", "unknown"}
    status_filter = status.lower() if status else "all"
    if status_filter not in valid_statuses:
        status_filter = "all"

    product_status_options = [
        {"value": "all", "label": "All products"},
        {"value": "active", "label": "Active"},
        {"value": "draft", "label": "Draft"},
        {"value": "sold", "label": "Sold"},
        {"value": "archived", "label": "Archived"},
    ]

    normalized_product_status = (product_status or "active").lower()
    valid_product_status_values = {opt["value"] for opt in product_status_options}
    if normalized_product_status not in valid_product_status_values:
        normalized_product_status = "active"

    async with get_session() as db:
        stmt = (
            select(
                Product.id.label("product_id"),
                Product.sku,
                Product.brand,
                Product.model,
                Product.title,
                Product.primary_image,
                Product.status.label("product_status"),
                PlatformCommon.id.label("platform_id"),
                PlatformCommon.external_id.label("ebay_item_id"),
                PlatformCommon.listing_url,
                PlatformCommon.status.label("platform_status"),
                PlatformCommon.updated_at.label("platform_updated_at"),
                EbayListing.listing_status,
                EbayListing.updated_at.label("listing_updated_at"),
                EbayListing.listing_data["uses_crazylister"].astext.label("uses_crazylister"),
            )
            .join(PlatformCommon, PlatformCommon.product_id == Product.id)
            .join(EbayListing, EbayListing.platform_id == PlatformCommon.id)
            .where(PlatformCommon.platform_name == "ebay")
            .order_by(func.coalesce(EbayListing.updated_at, PlatformCommon.updated_at).desc())
        )

        if normalized_product_status != "all":
            stmt = stmt.where(Product.status == normalized_product_status.upper())

        if search:
            search_term = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    Product.sku.ilike(search_term),
                    Product.brand.ilike(search_term),
                    Product.model.ilike(search_term),
                    Product.title.ilike(search_term),
                )
            )

        result = await db.execute(stmt)
        rows = result.fetchall()

    def classify_flag(raw_value: Any) -> str:
        if raw_value is None:
            return "unknown"
        if isinstance(raw_value, bool):
            return "applied" if raw_value else "missing"
        normalized = str(raw_value).strip().lower()
        if normalized in {"true", "1", "yes"}:
            return "applied"
        if normalized in {"false", "0", "no"}:
            return "missing"
        return "unknown"

    prepared_rows = []
    summary_counts = {"applied": 0, "missing": 0, "unknown": 0}

    for row in rows:
        mapping = row._mapping
        template_status = classify_flag(mapping.get("uses_crazylister"))
        summary_counts[template_status] += 1

        last_refreshed = mapping.get("listing_updated_at") or mapping.get("platform_updated_at")

        prepared_rows.append({
            "product_id": mapping.get("product_id"),
            "platform_id": mapping.get("platform_id"),
            "sku": mapping.get("sku"),
            "brand": mapping.get("brand"),
            "model": mapping.get("model"),
            "title": mapping.get("title"),
            "primary_image": mapping.get("primary_image"),
            "product_status": mapping.get("product_status"),
            "platform_status": mapping.get("platform_status"),
            "listing_status": mapping.get("listing_status"),
            "ebay_item_id": mapping.get("ebay_item_id"),
            "listing_url": mapping.get("listing_url"),
            "template_status": template_status,
            "last_refreshed": last_refreshed,
        })

    filtered_rows = (
        prepared_rows if status_filter == "all"
        else [row for row in prepared_rows if row["template_status"] == status_filter]
    )

    summary_counts["total"] = len(prepared_rows)
    coverage_pct = 0.0
    if summary_counts["total"]:
        coverage_pct = (summary_counts["applied"] / summary_counts["total"]) * 100

    status_options = [
        {"value": "all", "label": "All statuses"},
        {"value": "applied", "label": "Template applied"},
        {"value": "missing", "label": "Missing template"},
        {"value": "unknown", "label": "Unknown / not refreshed"},
    ]

    return templates.TemplateResponse("reports/crazylister_coverage.html", {
        "request": request,
        "rows": filtered_rows,
        "status_filter": status_filter,
        "status_options": status_options,
        "product_status_filter": normalized_product_status,
        "product_status_options": product_status_options,
        "search_query": search or "",
        "summary_counts": summary_counts,
        "coverage_pct": coverage_pct,
        "filtered_count": len(filtered_rows),
    })


@router.post("/crazylister-coverage/{platform_id}/refresh")
async def refresh_single_crazylister_listing(
    platform_id: int,
    settings: Settings = Depends(get_settings),
):
    async with get_session() as db:
        service = EbayService(db, settings)
        result = await service.refresh_single_listing_metadata(platform_id=platform_id, dry_run=False)

    if result["status"] == "missing":
        raise HTTPException(status_code=404, detail=result.get("message", "Listing not found"))

    return result


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
        
        -- Status mappings (case-insensitive)
        LEFT JOIN platform_status_mappings psm_a ON psm_a.platform_name = :platform_a AND (
            (:platform_a = 'reverb' AND psm_a.platform_status = LOWER(rl_a.reverb_state)) OR
            (:platform_a = 'vr' AND psm_a.platform_status = LOWER(vl_a.vr_state)) OR
            (:platform_a = 'ebay' AND psm_a.platform_status = LOWER(el_a.listing_status)) OR
            (:platform_a = 'shopify' AND psm_a.platform_status = LOWER(sl_a.status))
        )
        LEFT JOIN platform_status_mappings psm_b ON psm_b.platform_name = :platform_b AND (
            (:platform_b = 'reverb' AND psm_b.platform_status = LOWER(rl_b.reverb_state)) OR
            (:platform_b = 'vr' AND psm_b.platform_status = LOWER(vl_b.vr_state)) OR
            (:platform_b = 'ebay' AND psm_b.platform_status = LOWER(el_b.listing_status)) OR
            (:platform_b = 'shopify' AND psm_b.platform_status = LOWER(sl_b.status))
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
                        AND pc_shopify.status NOT IN ('sold', 'ended')
                    ) THEN 1 ELSE 0 END as has_shopify,
                    
                    CASE WHEN EXISTS (
                        SELECT 1 FROM platform_common pc_ebay 
                        WHERE pc_ebay.product_id = p.id 
                        AND pc_ebay.platform_name = 'ebay'
                        AND pc_ebay.status NOT IN ('sold', 'ended')
                    ) THEN 1 ELSE 0 END as has_ebay,
                    
                    CASE WHEN EXISTS (
                        SELECT 1 FROM platform_common pc_vr 
                        WHERE pc_vr.product_id = p.id 
                        AND pc_vr.platform_name = 'vr'
                        AND pc_vr.status NOT IN ('sold', 'ended')
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
        "new_listing", "price_change", "status_change", "removed_listing", "order_sale", "title", "description"
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


@router.delete("/sync-events/clear-pending", response_class=JSONResponse)
async def clear_pending_sync_events(
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    """
    Delete all pending sync events from the database.
    Used to clear stale events from API sync issues.
    """
    async with get_session() as db:
        # Count before delete for feedback
        count_query = text("SELECT COUNT(*) FROM sync_events WHERE status = 'pending'")
        count_result = await db.execute(count_query)
        pending_count = count_result.scalar()

        if pending_count == 0:
            return JSONResponse({
                "status": "info",
                "message": "No pending events to clear.",
                "deleted_count": 0
            })

        # Delete all pending events
        delete_query = text("DELETE FROM sync_events WHERE status = 'pending'")
        await db.execute(delete_query)
        await db.commit()

        return JSONResponse({
            "status": "success",
            "message": f"Cleared {pending_count} pending sync event(s).",
            "deleted_count": pending_count
        })


@router.get("/archive-status-sync", response_class=HTMLResponse)
async def archive_status_sync_report(request: Request):
    """
    Archive Status Sync Report: Find products that should be ARCHIVED at product level.

    Criteria:
    - Shopify listing exists AND status = ARCHIVED
    - Product status = ACTIVE (mismatch)
    - No active listings on other platforms (Reverb, eBay, V&R)

    Products with status = SOLD are excluded (we don't downgrade SOLD to ARCHIVED).
    """
    async with get_session() as db:
        # Find mismatched products: Shopify ARCHIVED but Product ACTIVE, not on other platforms
        query = text("""
            SELECT
                p.id as product_id,
                p.sku,
                p.brand,
                p.model,
                p.status as product_status,
                p.primary_image,
                p.created_at,
                sl.shopify_product_id,
                sl.status as shopify_status,
                sl.updated_at as shopify_updated_at,
                pc_shopify.external_id as shopify_external_id
            FROM products p
            INNER JOIN platform_common pc_shopify
                ON pc_shopify.product_id = p.id
                AND pc_shopify.platform_name = 'shopify'
            INNER JOIN shopify_listings sl
                ON sl.platform_id = pc_shopify.id
            WHERE UPPER(sl.status) = 'ARCHIVED'
              AND p.status = 'ACTIVE'
              AND NOT EXISTS (
                  SELECT 1 FROM platform_common pc2
                  WHERE pc2.product_id = p.id
                  AND pc2.platform_name IN ('reverb', 'ebay', 'vr')
                  AND UPPER(pc2.status) IN ('ACTIVE', 'LIVE')
              )
            ORDER BY sl.updated_at DESC
            LIMIT 500;
        """)

        result = await db.execute(query)
        mismatched_products = [dict(row._mapping) for row in result.fetchall()]

        # Get count of already correct (SOLD products with ARCHIVED Shopify - these are fine)
        sold_archived_query = text("""
            SELECT COUNT(*) as count
            FROM products p
            INNER JOIN platform_common pc_shopify
                ON pc_shopify.product_id = p.id
                AND pc_shopify.platform_name = 'shopify'
            INNER JOIN shopify_listings sl
                ON sl.platform_id = pc_shopify.id
            WHERE UPPER(sl.status) = 'ARCHIVED'
              AND p.status = 'SOLD'
        """)
        sold_result = await db.execute(sold_archived_query)
        sold_archived_count = sold_result.scalar()

    return templates.TemplateResponse("reports/archive_status_sync.html", {
        "request": request,
        "products": mismatched_products,
        "mismatch_count": len(mismatched_products),
        "sold_archived_count": sold_archived_count,
    })


@router.post("/archive-status-sync/archive/{product_id}", response_class=JSONResponse)
async def archive_single_product(product_id: int):
    """Archive a single product (set status to ARCHIVED)."""
    async with get_session() as db:
        # Verify product exists and is ACTIVE
        product = await db.get(Product, product_id)
        if not product:
            return JSONResponse({"status": "error", "message": "Product not found"}, status_code=404)

        if product.status == ProductStatus.SOLD:
            return JSONResponse({"status": "error", "message": "Cannot archive SOLD products"}, status_code=400)

        if product.status == ProductStatus.ARCHIVED:
            return JSONResponse({"status": "info", "message": "Product already archived"})

        # Update to ARCHIVED
        product.status = ProductStatus.ARCHIVED
        await db.commit()

        return JSONResponse({
            "status": "success",
            "message": f"Product {product.sku} archived successfully"
        })


@router.post("/archive-status-sync/archive-all", response_class=JSONResponse)
async def archive_all_mismatched():
    """Archive all mismatched products (ACTIVE with Shopify ARCHIVED, not on other platforms)."""
    async with get_session() as db:
        # Get all mismatched product IDs
        query = text("""
            SELECT p.id
            FROM products p
            INNER JOIN platform_common pc_shopify
                ON pc_shopify.product_id = p.id
                AND pc_shopify.platform_name = 'shopify'
            INNER JOIN shopify_listings sl
                ON sl.platform_id = pc_shopify.id
            WHERE UPPER(sl.status) = 'ARCHIVED'
              AND p.status = 'ACTIVE'
              AND NOT EXISTS (
                  SELECT 1 FROM platform_common pc2
                  WHERE pc2.product_id = p.id
                  AND pc2.platform_name IN ('reverb', 'ebay', 'vr')
                  AND UPPER(pc2.status) IN ('ACTIVE', 'LIVE')
              )
        """)

        result = await db.execute(query)
        product_ids = [row[0] for row in result.fetchall()]

        if not product_ids:
            return JSONResponse({"status": "info", "message": "No products to archive", "archived_count": 0})

        # Update all to ARCHIVED
        update_query = text("""
            UPDATE products
            SET status = 'ARCHIVED', updated_at = NOW()
            WHERE id = ANY(:ids)
        """)
        await db.execute(update_query, {"ids": product_ids})
        await db.commit()

        return JSONResponse({
            "status": "success",
            "message": f"Archived {len(product_ids)} product(s)",
            "archived_count": len(product_ids)
        })


@router.get("/platform-coverage", response_class=HTMLResponse)
async def platform_coverage_report(
    request: Request,
    sort_by: Optional[str] = Query("missing_count", description="Sort by column"),
    sort_order: Optional[str] = Query("desc", description="Sort order (asc/desc)")
):
    """
    Platform Coverage Report: Identify ACTIVE products missing from certain platforms.
    """
    async with get_session() as db:
        # Only show ACTIVE products
        status_clause = "WHERE p.status = 'ACTIVE'"
        params = {}
        
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
                p.category,
                COALESCE(ARRAY_AGG(pc.platform_name) FILTER (WHERE pc.platform_name IS NOT NULL), ARRAY[]::text[]) AS platforms
            FROM products p
            LEFT JOIN platform_common pc ON p.id = pc.product_id
                AND (pc.status NOT IN ('sold', 'ended') OR pc.status IS NULL)
            {status_clause}
            GROUP BY p.id, p.sku, p.brand, p.model, p.base_price, p.status, p.category
        ),
        vr_eligible AS (
            -- Check which categories have VR mappings (have a vintageandrare target row)
            SELECT DISTINCT source_category_name
            FROM platform_category_mappings
            WHERE source_platform = 'reverb' AND target_platform = 'vintageandrare'
        ),
        coverage_data AS (
            SELECT
                pc.product_id,
                pc.sku,
                pc.brand,
                pc.model,
                pc.base_price,
                pc.status,
                pc.platforms,
                CASE
                    WHEN ARRAY_LENGTH(pc.platforms, 1) IS NULL THEN 0
                    ELSE ARRAY_LENGTH(pc.platforms, 1)
                END AS platform_count,
                -- Only include 'vr' in expected platforms if category has VR mapping AND is not excluded
                -- Excluded categories: Pro Audio (all), Accessories / Headphones
                -- (per add.html checkProAudioCategory and business rules)
                ARRAY(
                    SELECT unnest(
                        CASE
                            WHEN ve.source_category_name IS NOT NULL
                                 AND pc.category NOT LIKE 'Pro Audio%'
                                 AND pc.category != 'Accessories / Headphones'
                            THEN ARRAY['shopify', 'ebay', 'reverb', 'vr']
                            ELSE ARRAY['shopify', 'ebay', 'reverb']
                        END
                    )
                    EXCEPT
                    SELECT unnest(pc.platforms)
                ) AS missing_platforms,
                CASE
                    WHEN ve.source_category_name IS NOT NULL
                         AND pc.category NOT LIKE 'Pro Audio%'
                         AND pc.category != 'Accessories / Headphones' THEN 4
                    ELSE 3
                END AS max_platforms
            FROM platform_coverage pc
            LEFT JOIN vr_eligible ve ON pc.category = ve.source_category_name
        )
        SELECT
            product_id, sku, brand, model, base_price, status, platforms, platform_count,
            missing_platforms,
            ARRAY_LENGTH(missing_platforms, 1) AS missing_count
        FROM coverage_data
        WHERE ARRAY_LENGTH(missing_platforms, 1) > 0
        ORDER BY {sort_col} {sort_dir},
                 ARRAY_TO_STRING(missing_platforms, ',') ASC,
                 sku ASC;
        """)
        
        result = await db.execute(query, params)
        coverage_data = [dict(row._mapping) for row in result.fetchall()]

        return templates.TemplateResponse("reports/platform_coverage.html", {
            "request": request,
            "coverage_data": coverage_data,
            "sort_by": sort_by,
            "sort_order": sort_order
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

            if action == 'skip':
                # Mark event as skipped without any further processing
                event.status = 'skipped'
                event.processed_at = datetime.utcnow()
                await db.commit()
                return {
                    "status": "success",
                    "message": f"Event {event_id} marked as skipped"
                }

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

            if action == 'activate_listing':
                return await _activate_listing_status(db, event)

            if action == 'relist':
                # Flow 1: Reverb relisted, propagate to other platforms
                return await _relist_from_reverb(db, event)

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


async def _activate_listing_status(db: AsyncSession, event: SyncEvent) -> Dict[str, Any]:
    """Force a Reverb listing to active/live locally when the API reports it as such."""
    platform_name = (event.platform_name or '').lower()
    if platform_name != 'reverb':
        return {
            "status": "error",
            "message": "Manual activation is currently available for Reverb listings only"
        }

    if event.change_type != 'status_change':
        return {
            "status": "error",
            "message": "Manual activation is limited to status change events"
        }

    change_data = event.change_data or {}
    desired_status = str(change_data.get('new') or '').lower()
    if desired_status not in {'live', 'active'}:
        return {
            "status": "error",
            "message": f"Cannot activate status '{desired_status or 'unknown'}'"
        }

    platform_listing: Optional[PlatformCommon] = None
    if event.platform_common_id:
        platform_listing = await db.get(PlatformCommon, event.platform_common_id)

    if not platform_listing and event.external_id:
        stmt = select(PlatformCommon).where(
            PlatformCommon.platform_name == 'reverb',
            PlatformCommon.external_id == str(event.external_id)
        )
        result = await db.execute(stmt)
        platform_listing = result.scalar_one_or_none()

    if not platform_listing and event.product_id:
        stmt = select(PlatformCommon).where(
            PlatformCommon.platform_name == 'reverb',
            PlatformCommon.product_id == event.product_id
        )
        result = await db.execute(stmt)
        platform_listing = result.scalar_one_or_none()

    if not platform_listing:
        return {
            "status": "error",
            "message": "Unable to locate platform_common entry for this event"
        }

    now_utc = datetime.utcnow()
    platform_listing.status = ListingStatus.ACTIVE.value
    platform_listing.sync_status = SyncStatus.SYNCED.value
    platform_listing.last_sync = now_utc
    platform_listing.updated_at = now_utc
    db.add(platform_listing)

    reverb_listing: Optional[ReverbListing] = None
    if platform_listing.id:
        stmt = select(ReverbListing).where(ReverbListing.platform_id == platform_listing.id)
        result = await db.execute(stmt)
        reverb_listing = result.scalar_one_or_none()

    if not reverb_listing and platform_listing.external_id:
        stmt = select(ReverbListing).where(ReverbListing.reverb_listing_id == platform_listing.external_id)
        result = await db.execute(stmt)
        reverb_listing = result.scalar_one_or_none()

    if reverb_listing:
        reverb_listing.reverb_state = 'live'
        reverb_listing.last_synced_at = now_utc
        reverb_listing.updated_at = now_utc
        db.add(reverb_listing)

    event.status = 'processed'
    event.processed_at = now_utc
    notes_msg = "Manually marked as live via Sync Events UI"
    event.notes = f"{event.notes}\n{notes_msg}" if event.notes else notes_msg
    db.add(event)

    await db.commit()

    return {
        "status": "success",
        "message": "Local listing marked active and event closed",
        "details": {
            "platform_common_id": platform_listing.id,
            "reverb_listing_id": getattr(reverb_listing, 'id', None)
        }
    }


async def _relist_from_reverb(db: AsyncSession, event: SyncEvent) -> Dict[str, Any]:
    """
    Flow 1: Reverb listing was relisted (status changed to active/live).
    Propagate the relist to other platforms (eBay, Shopify, V&R).

    This uses the EventProcessor._process_status_change() method which handles:
    - eBay: RelistFixedPriceItem (creates new ItemID, orphans old listing)
    - Shopify: Set to ACTIVE with inventory=1
    - V&R: restore_from_sold
    """
    from app.services.event_processor import EventProcessor

    platform_name = (event.platform_name or '').lower()
    if platform_name != 'reverb':
        return {
            "status": "error",
            "message": "Relist propagation is only available for Reverb status changes"
        }

    if event.change_type != 'status_change':
        return {
            "status": "error",
            "message": "Relist is only available for status change events"
        }

    change_data = event.change_data or {}
    new_status = str(change_data.get('new') or '').lower()
    if new_status not in {'live', 'active'}:
        return {
            "status": "error",
            "message": f"Cannot relist - new status is '{new_status or 'unknown'}', expected 'live' or 'active'"
        }

    if not event.product_id:
        return {
            "status": "error",
            "message": "Cannot relist - no product_id associated with this event"
        }

    # Use the EventProcessor to handle the relist propagation
    processor = EventProcessor(db, dry_run=False)
    result = await processor.process_sync_event(event)

    if result.success:
        # Mark event as processed
        now_utc = datetime.utcnow()
        event.status = 'processed'
        event.processed_at = now_utc
        notes_msg = f"Relisted via Sync Events UI. Platforms: {', '.join(result.platforms_created) if result.platforms_created else 'none'}"
        if result.platforms_failed:
            notes_msg += f". Failed: {', '.join(result.platforms_failed)}"
        event.notes = f"{event.notes}\n{notes_msg}" if event.notes else notes_msg
        db.add(event)
        await db.commit()

        return {
            "status": "success" if not result.platforms_failed else "partial",
            "message": result.message,
            "details": {
                "product_id": result.product_id,
                "platforms_created": result.platforms_created,
                "platforms_failed": result.platforms_failed,
                "errors": result.errors
            }
        }
    else:
        return {
            "status": "error",
            "message": result.message,
            "details": {
                "errors": result.errors,
                "platforms_failed": result.platforms_failed
            }
        }


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
        # Logic:
        # - If a platform shows 'sold' status (is_sold=True), that's where it sold
        # - If all platforms only show 'ended' (is_sold=False), it's an offline/private sale
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
                    COALESCE((se.change_data->>'is_sold')::boolean, false) as is_sold,
                    ROW_NUMBER() OVER (
                        PARTITION BY p.id, DATE(se.detected_at)
                        ORDER BY
                            -- Prioritize 'sold' over 'ended' events
                            CASE WHEN se.change_data->>'new' = 'sold' THEN 0 ELSE 1 END,
                            se.detected_at DESC
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

                    -- Determine sale platform based on actual sale indicators
                    CASE
                        -- If this platform explicitly shows 'sold' with is_sold=True, it sold there
                        WHEN rs.change_type = 'sold' OR rs.is_sold = true
                        THEN rs.reporting_platform

                        -- Check if ANY platform reported an actual sale for this product
                        WHEN EXISTS (
                            SELECT 1 FROM sync_events se2
                            WHERE se2.product_id = rs.product_id
                            AND se2.change_type = 'status_change'
                            AND (se2.change_data->>'new' = 'sold'
                                 OR (se2.change_data->>'is_sold')::boolean = true)
                        )
                        THEN (
                            -- Return the platform that actually sold it
                            SELECT se2.platform_name FROM sync_events se2
                            WHERE se2.product_id = rs.product_id
                            AND se2.change_type = 'status_change'
                            AND (se2.change_data->>'new' = 'sold'
                                 OR (se2.change_data->>'is_sold')::boolean = true)
                            ORDER BY se2.detected_at DESC
                            LIMIT 1
                        )

                        -- No platform shows actual sale - it's an offline/private sale
                        ELSE 'offline'
                    END as sale_platform

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

            # Ensure IDs are integers (fix for "str cannot be interpreted as integer" error)
            product1_dict = dict(product1_row)
            product2_dict = dict(product2_row)
            product1_dict['id'] = int(product1_dict['id'])
            product1_dict['platform_common_id'] = int(product1_dict['platform_common_id'])
            product2_dict['id'] = int(product2_dict['id'])
            product2_dict['platform_common_id'] = int(product2_dict['platform_common_id'])

            match = {
                f"{platform1}_product": product1_dict,
                f"{platform2}_product": product2_dict,
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


@router.get("/inventory-reconciliation", response_class=HTMLResponse)
async def inventory_reconciliation_report(request: Request):
    """
    Show all inventoried (stocked) items with quantities across all platforms.
    Allows reconciliation of quantities to match RIFF as the source of truth.
    """
    async with get_session() as db:
        # Get all stocked items with their platform quantities
        query = text("""
            SELECT
                p.id,
                p.sku,
                p.title,
                p.quantity as riff_qty,
                p.primary_image,
                rl.inventory_quantity as reverb_qty,
                rl.reverb_listing_id,
                el.quantity_available as ebay_qty,
                el.ebay_item_id,
                CASE WHEN sl.id IS NOT NULL THEN true ELSE false END as shopify_listed,
                sl.shopify_product_id,
                sl.handle as shopify_handle,
                sl.extended_attributes as shopify_extended,
                CASE WHEN vl.id IS NOT NULL THEN true ELSE false END as vr_listed,
                vl.vr_listing_id,
                pc_reverb.status as reverb_status,
                pc_ebay.status as ebay_status,
                pc_shopify.status as shopify_status,
                pc_vr.status as vr_status
            FROM products p
            LEFT JOIN platform_common pc_reverb ON pc_reverb.product_id = p.id AND pc_reverb.platform_name = 'reverb'
            LEFT JOIN reverb_listings rl ON rl.platform_id = pc_reverb.id
            LEFT JOIN platform_common pc_ebay ON pc_ebay.product_id = p.id AND pc_ebay.platform_name = 'ebay'
            LEFT JOIN ebay_listings el ON el.platform_id = pc_ebay.id
            LEFT JOIN platform_common pc_shopify ON pc_shopify.product_id = p.id AND pc_shopify.platform_name = 'shopify'
            LEFT JOIN shopify_listings sl ON sl.platform_id = pc_shopify.id
            LEFT JOIN platform_common pc_vr ON pc_vr.product_id = p.id AND pc_vr.platform_name = 'vr'
            LEFT JOIN vr_listings vl ON vl.platform_id = pc_vr.id
            WHERE p.is_stocked_item = true
            AND p.status = 'ACTIVE'
            ORDER BY p.title
        """)

        result = await db.execute(query)
        rows = result.fetchall()

        items = []
        out_of_sync_count = 0

        for row in rows:
            row_dict = row._mapping

            # Check if quantities are in sync
            riff_qty = row_dict['riff_qty'] or 0
            reverb_qty = row_dict['reverb_qty']
            ebay_qty = row_dict['ebay_qty']

            # Extract Shopify quantity from extended_attributes
            shopify_qty = None
            shopify_extended = row_dict.get('shopify_extended')
            if shopify_extended and isinstance(shopify_extended, dict):
                # Prefer totalInventory as the authoritative value
                shopify_qty = shopify_extended.get('totalInventory')
                # Fallback to variants if totalInventory not present
                if shopify_qty is None:
                    variants = shopify_extended.get('variants', {})
                    nodes = variants.get('nodes', [])
                    if nodes and len(nodes) > 0:
                        shopify_qty = nodes[0].get('inventoryQuantity')
                    # Also check edges[].node structure (older format)
                    if shopify_qty is None:
                        edges = variants.get('edges', [])
                        if edges and len(edges) > 0:
                            node = edges[0].get('node', {})
                            shopify_qty = node.get('inventoryQuantity')

            # Consider out of sync if any active platform has different qty
            is_synced = True
            if reverb_qty is not None and reverb_qty != riff_qty:
                is_synced = False
            if ebay_qty is not None and ebay_qty != riff_qty:
                is_synced = False
            if shopify_qty is not None and shopify_qty != riff_qty:
                is_synced = False

            if not is_synced:
                out_of_sync_count += 1

            items.append({
                'id': row_dict['id'],
                'sku': row_dict['sku'],
                'title': row_dict['title'],
                'primary_image': row_dict['primary_image'],
                'riff_qty': riff_qty,
                'reverb_qty': reverb_qty,
                'reverb_listing_id': row_dict['reverb_listing_id'],
                'reverb_status': row_dict['reverb_status'],
                'ebay_qty': ebay_qty,
                'ebay_item_id': row_dict['ebay_item_id'],
                'ebay_status': row_dict['ebay_status'],
                'shopify_listed': row_dict['shopify_listed'],
                'shopify_product_id': row_dict['shopify_product_id'],
                'shopify_handle': row_dict['shopify_handle'],
                'shopify_qty': shopify_qty,
                'shopify_status': row_dict['shopify_status'],
                'vr_listed': row_dict['vr_listed'],
                'vr_listing_id': row_dict['vr_listing_id'],
                'vr_status': row_dict['vr_status'],
                'is_synced': is_synced,
            })

        return templates.TemplateResponse("reports/inventory_reconciliation.html", {
            "request": request,
            "items": items,
            "total_count": len(items),
            "out_of_sync_count": out_of_sync_count,
        })


@router.post("/inventory-reconciliation/reconcile/{product_id}")
async def reconcile_inventory(product_id: int, request: Request):
    """
    Smart reconciliation for stocked items.

    Flow:
    1. Check each platform's ACTUAL remote quantity
    2. If remote matches RIFF target qty -> just update local DB (no API call)
    3. If remote differs from RIFF target qty -> push update to that platform only
    4. Only update RIFF if the new_quantity differs from current
    """
    from fastapi.responses import JSONResponse
    from app.models.reverb import ReverbListing
    from app.models.ebay import EbayListing
    from app.models.shopify import ShopifyListing
    from app.services.shopify.client import ShopifyGraphQLClient
    from datetime import datetime

    try:
        body = await request.json()
        target_quantity = int(body.get('quantity', 0))
    except (ValueError, TypeError):
        return JSONResponse({"status": "error", "message": "Invalid quantity"}, status_code=400)

    from app.core.config import get_settings
    settings = get_settings()

    async with get_session() as db:
        product = await db.get(Product, product_id)
        if not product:
            return JSONResponse({"status": "error", "message": "Product not found"}, status_code=404)

        if not product.is_stocked_item:
            return JSONResponse({"status": "error", "message": "Product is not a stocked item"}, status_code=400)

        results = {"riff": "unchanged", "reverb": "skipped", "ebay": "skipped", "shopify": "skipped"}

        # Update RIFF if needed
        if product.quantity != target_quantity:
            product.quantity = target_quantity
            results["riff"] = f"updated to {target_quantity}"

        # Get platform links
        platform_links = (
            await db.execute(
                select(PlatformCommon).where(PlatformCommon.product_id == product_id)
            )
        ).scalars().all()

        vr_executor = getattr(request.app.state, "vr_executor", None)

        for link in platform_links:
            try:
                if link.platform_name == "reverb":
                    # Check Reverb
                    listing_result = await db.execute(
                        select(ReverbListing).where(ReverbListing.platform_id == link.id)
                    )
                    listing = listing_result.scalar_one_or_none()
                    if listing:
                        if listing.inventory_quantity != target_quantity:
                            # Need to update Reverb - use apply_product_update with quantity change
                            from app.services.reverb_service import ReverbService
                            reverb_service = ReverbService(db, settings)
                            # Ensure product quantity is set to target for the update
                            product.quantity = target_quantity
                            result = await reverb_service.apply_product_update(product, link, {"quantity"})
                            if result.get("status") != "error":
                                listing.inventory_quantity = target_quantity
                                listing.last_synced_at = datetime.utcnow()
                                results["reverb"] = f"updated to {target_quantity}"
                            else:
                                results["reverb"] = f"update failed: {result.get('message', 'unknown')}"
                        else:
                            results["reverb"] = "already correct"

                elif link.platform_name == "ebay":
                    # Check eBay
                    listing_result = await db.execute(
                        select(EbayListing).where(EbayListing.platform_id == link.id)
                    )
                    listing = listing_result.scalar_one_or_none()
                    if listing:
                        if listing.quantity_available != target_quantity:
                            # Need to update eBay
                            from app.services.ebay_service import EbayService
                            ebay_service = EbayService(db, settings)
                            success = await ebay_service.update_listing_quantity(
                                listing.ebay_item_id, target_quantity
                            )
                            if success:
                                listing.quantity_available = target_quantity
                                listing.last_synced_at = datetime.utcnow()
                                results["ebay"] = f"updated to {target_quantity}"
                            else:
                                results["ebay"] = "update failed"
                        else:
                            results["ebay"] = "already correct"

                elif link.platform_name == "shopify":
                    # Check Shopify - need to poll actual remote qty
                    listing_result = await db.execute(
                        select(ShopifyListing).where(ShopifyListing.platform_id == link.id)
                    )
                    listing = listing_result.scalar_one_or_none()
                    if listing and listing.shopify_product_id:
                        # Get actual Shopify qty
                        shopify_client = ShopifyGraphQLClient()
                        query = """
                        query getProduct($id: ID!) {
                          product(id: $id) {
                            totalInventory
                          }
                        }
                        """
                        response = shopify_client.execute(query, {'id': listing.shopify_product_id})
                        product_data = response.get('product') or (response.get('data', {}) or {}).get('product')
                        actual_shopify_qty = product_data.get('totalInventory') if product_data else None

                        if actual_shopify_qty is not None and actual_shopify_qty != target_quantity:
                            # Need to update Shopify
                            from app.services.shopify_service import ShopifyService
                            shopify_service = ShopifyService(db, shopify_client)
                            # Ensure product quantity is set to target for the update
                            product.quantity = target_quantity
                            # Use apply_product_update which handles inventory
                            await shopify_service.apply_product_update(product, link, {"quantity"})
                            results["shopify"] = f"updated to {target_quantity}"
                        else:
                            # Remote is correct, just update local extended_attributes if stale
                            if listing.extended_attributes:
                                ext = dict(listing.extended_attributes)

                                # Check current local qty (handle both nodes[] and edges[].node structures)
                                variants = ext.get('variants', {})
                                local_qty = ext.get('totalInventory')
                                nodes = variants.get('nodes', [])
                                edges = variants.get('edges', [])

                                if local_qty is None and nodes:
                                    local_qty = nodes[0].get('inventoryQuantity')
                                if local_qty is None and edges:
                                    local_qty = edges[0].get('node', {}).get('inventoryQuantity')

                                if local_qty != target_quantity:
                                    # Update totalInventory
                                    ext['totalInventory'] = target_quantity
                                    # Update nodes structure if present
                                    if nodes:
                                        nodes[0]['inventoryQuantity'] = target_quantity
                                        ext['variants']['nodes'] = nodes
                                    # Update edges structure if present
                                    if edges:
                                        edges[0]['node']['inventoryQuantity'] = target_quantity
                                        ext['variants']['edges'] = edges
                                    listing.extended_attributes = ext
                                    listing.last_synced_at = datetime.utcnow()
                                    results["shopify"] = "local data corrected"
                                else:
                                    results["shopify"] = "already correct"
                            else:
                                results["shopify"] = "already correct"

            except Exception as exc:
                logger.error("Error reconciling %s for product %s: %s", link.platform_name, product.sku, exc)
                results[link.platform_name] = f"error: {str(exc)[:50]}"

        await db.commit()

        logger.info("Smart reconciliation for product %s: %s", product.sku, results)

        return JSONResponse({
            "status": "success",
            "message": f"Reconciliation complete",
            "target_quantity": target_quantity,
            "results": results,
        })


@router.get("/listing-engagement", response_class=HTMLResponse)
async def listing_engagement_report(
    request: Request,
    sort_by: str = Query("total_watches", description="Sort field"),
    sort_order: str = Query("desc", description="Sort order"),
    search: Optional[str] = Query(None, description="Search by brand, model, or SKU"),
    min_watches: Optional[int] = Query(None, description="Minimum watch count"),
):
    """
    Listing Engagement Report: Analyze views, watches, and engagement metrics
    across platforms, aggregated by product/SKU.
    """
    from datetime import timedelta

    # Valid sort columns
    valid_sort_cols = ["total_watches", "total_views", "watch_change_7d", "view_change_7d", "price", "days_listed"]
    sort_by = sort_by.lower() if sort_by.lower() in valid_sort_cols else "total_watches"
    sort_order = "asc" if sort_order.lower() == "asc" else "desc"

    async with get_session() as db:
        now = datetime.utcnow()
        seven_days_ago = now - timedelta(days=7)

        # Query aggregates stats by product, combining Reverb and eBay data
        stats_sql = """
        WITH latest_stats AS (
            SELECT DISTINCT ON (platform, platform_listing_id)
                lsh.platform,
                lsh.platform_listing_id,
                lsh.product_id,
                lsh.view_count,
                lsh.watch_count,
                lsh.price,
                lsh.state,
                lsh.recorded_at
            FROM listing_stats_history lsh
            WHERE lsh.recorded_at >= :cutoff_date
            ORDER BY platform, platform_listing_id, recorded_at DESC
        ),
        week_ago_stats AS (
            SELECT DISTINCT ON (platform, platform_listing_id)
                lsh.platform,
                lsh.platform_listing_id,
                lsh.view_count as old_view_count,
                lsh.watch_count as old_watch_count
            FROM listing_stats_history lsh
            WHERE lsh.recorded_at >= :week_ago_start
              AND lsh.recorded_at < :week_ago_end
            ORDER BY platform, platform_listing_id, recorded_at DESC
        ),
        stats_with_change AS (
            SELECT
                ls.platform,
                ls.platform_listing_id,
                ls.product_id,
                COALESCE(ls.view_count, 0) as view_count,
                COALESCE(ls.watch_count, 0) as watch_count,
                ls.price,
                COALESCE(ls.view_count, 0) - COALESCE(ws.old_view_count, 0) as view_change,
                COALESCE(ls.watch_count, 0) - COALESCE(ws.old_watch_count, 0) as watch_change
            FROM latest_stats ls
            LEFT JOIN week_ago_stats ws ON ls.platform = ws.platform
                AND ls.platform_listing_id = ws.platform_listing_id
            WHERE ls.state IN ('live', 'Active', 'active')
              AND ls.product_id IS NOT NULL
        )
        SELECT
            p.id as product_id,
            p.sku,
            p.brand,
            p.model,
            p.primary_image,
            p.created_at as product_created_at,
            COALESCE(p.base_price, 0) as price,
            EXTRACT(EPOCH FROM (NOW() - p.created_at)) / 86400 as days_listed,
            -- Reverb stats
            MAX(CASE WHEN s.platform = 'reverb' THEN s.platform_listing_id END) as reverb_listing_id,
            COALESCE(MAX(CASE WHEN s.platform = 'reverb' THEN s.view_count END), 0) as reverb_views,
            COALESCE(MAX(CASE WHEN s.platform = 'reverb' THEN s.watch_count END), 0) as reverb_watches,
            COALESCE(MAX(CASE WHEN s.platform = 'reverb' THEN s.view_change END), 0) as reverb_view_change,
            COALESCE(MAX(CASE WHEN s.platform = 'reverb' THEN s.watch_change END), 0) as reverb_watch_change,
            -- eBay stats
            MAX(CASE WHEN s.platform = 'ebay' THEN s.platform_listing_id END) as ebay_listing_id,
            COALESCE(MAX(CASE WHEN s.platform = 'ebay' THEN s.view_count END), 0) as ebay_views,
            COALESCE(MAX(CASE WHEN s.platform = 'ebay' THEN s.watch_count END), 0) as ebay_watches,
            COALESCE(MAX(CASE WHEN s.platform = 'ebay' THEN s.view_change END), 0) as ebay_view_change,
            COALESCE(MAX(CASE WHEN s.platform = 'ebay' THEN s.watch_change END), 0) as ebay_watch_change,
            -- Totals
            COALESCE(SUM(s.view_count), 0) as total_views,
            COALESCE(SUM(s.watch_count), 0) as total_watches,
            COALESCE(SUM(s.view_change), 0) as view_change_7d,
            COALESCE(SUM(s.watch_change), 0) as watch_change_7d
        FROM products p
        INNER JOIN stats_with_change s ON p.id = s.product_id
        WHERE 1=1
        """

        params = {
            "cutoff_date": now - timedelta(days=30),
            "week_ago_start": seven_days_ago - timedelta(days=1),
            "week_ago_end": seven_days_ago + timedelta(days=1),
        }

        # Add search filter
        if search:
            stats_sql += """ AND (
                LOWER(p.sku) LIKE LOWER(:search)
                OR LOWER(p.brand) LIKE LOWER(:search)
                OR LOWER(p.model) LIKE LOWER(:search)
            )"""
            params["search"] = f"%{search}%"

        # Group by product
        stats_sql += " GROUP BY p.id, p.sku, p.brand, p.model, p.primary_image, p.created_at, p.base_price"

        # Add minimum watches filter (on total)
        if min_watches:
            stats_sql += " HAVING COALESCE(SUM(s.watch_count), 0) >= :min_watches"
            params["min_watches"] = min_watches

        # Add sorting
        sort_column_map = {
            "total_watches": "total_watches",
            "total_views": "total_views",
            "watch_change_7d": "watch_change_7d",
            "view_change_7d": "view_change_7d",
            "price": "price",
            "days_listed": "days_listed",
        }
        sort_col = sort_column_map.get(sort_by, "total_watches")
        stats_sql += f" ORDER BY {sort_col} {sort_order.upper()} NULLS LAST"

        # Execute query
        result = await db.execute(text(stats_sql), params)
        rows = result.fetchall()

        # Process results
        listings = []
        total_views = 0
        total_watches = 0
        total_value = 0
        reverb_count = 0
        ebay_count = 0

        for row in rows:
            listing = {
                "product_id": row.product_id,
                "sku": row.sku or "Unknown",
                "brand": row.brand or "",
                "model": row.model or "",
                "primary_image": row.primary_image,
                "price": float(row.price or 0),
                "days_listed": int(row.days_listed or 0),
                # Reverb
                "reverb_listing_id": row.reverb_listing_id,
                "reverb_views": row.reverb_views or 0,
                "reverb_watches": row.reverb_watches or 0,
                "reverb_view_change": row.reverb_view_change or 0,
                "reverb_watch_change": row.reverb_watch_change or 0,
                # eBay
                "ebay_listing_id": row.ebay_listing_id,
                "ebay_views": row.ebay_views or 0,
                "ebay_watches": row.ebay_watches or 0,
                "ebay_view_change": row.ebay_view_change or 0,
                "ebay_watch_change": row.ebay_watch_change or 0,
                # Totals
                "total_views": row.total_views or 0,
                "total_watches": row.total_watches or 0,
                "view_change_7d": row.view_change_7d or 0,
                "watch_change_7d": row.watch_change_7d or 0,
            }

            listings.append(listing)

            # Aggregate stats
            total_views += listing["total_views"]
            total_watches += listing["total_watches"]
            total_value += listing["price"]
            if listing["reverb_listing_id"]:
                reverb_count += 1
            if listing["ebay_listing_id"]:
                ebay_count += 1

        # Calculate summary stats
        summary = {
            "total_products": len(listings),
            "total_views": total_views,
            "total_watches": total_watches,
            "total_value": total_value,
            "avg_views": round(total_views / len(listings), 1) if listings else 0,
            "avg_watches": round(total_watches / len(listings), 1) if listings else 0,
            "avg_price": round(total_value / len(listings), 0) if listings else 0,
            "reverb_count": reverb_count,
            "ebay_count": ebay_count,
        }

        return templates.TemplateResponse("reports/listing_engagement.html", {
            "request": request,
            "listings": listings,
            "summary": summary,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "search": search or "",
            "min_watches": min_watches,
        })
