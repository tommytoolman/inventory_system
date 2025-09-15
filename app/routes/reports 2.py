from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional, List, Dict, Any
from app.database import get_session
from app.core.templates import templates
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
                    
                    -- Extract data from extended_attributes JSON
                    (rl.extended_attributes->>'created_at')::timestamp as listing_date,
                    (rl.extended_attributes->'buyer_price'->>'amount')::decimal as reverb_price,
                    (rl.extended_attributes->'stats'->>'views')::int as views,
                    (rl.extended_attributes->'stats'->>'watches')::int as watches,
                    (rl.extended_attributes->>'offer_count')::int as offers,
                    
                    -- Calculate engagement metrics (NO DECIMALS)
                    ROUND(
                        (rl.extended_attributes->'stats'->>'views')::decimal / 
                        GREATEST(EXTRACT(days FROM (CURRENT_DATE - (rl.extended_attributes->>'created_at')::timestamp)) / 30, 1), 0
                    ) as views_per_month,
                    
                    -- Red flags
                    CASE 
                        WHEN COALESCE((rl.extended_attributes->'stats'->>'views')::int, 0) = 0 
                            AND COALESCE((rl.extended_attributes->'stats'->>'watches')::int, 0) = 0 
                            AND COALESCE((rl.extended_attributes->>'offer_count')::int, 0) = 0 
                        THEN 'DEAD_STOCK'
                        WHEN COALESCE((rl.extended_attributes->'stats'->>'views')::int, 0) > 50 
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
                AND rl.extended_attributes->>'created_at' IS NOT NULL
                AND (rl.extended_attributes->>'inventory')::int = 1
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
                        COALESCE((rl.extended_attributes->'stats'->>'views')::decimal, 0) / 
                        GREATEST(
                            COALESCE(EXTRACT(days FROM (CURRENT_DATE - rl.reverb_created_at)), 30) / 30, 
                            1
                        ), 
                        0
                    ) as views_per_month,
                    
                    -- Red flags
                    CASE 
                        WHEN COALESCE((rl.extended_attributes->'stats'->>'views')::int, 0) = 0 
                            AND COALESCE((rl.extended_attributes->'stats'->>'watches')::int, 0) = 0 
                            AND COALESCE((rl.extended_attributes->>'offer_count')::int, 0) = 0 
                        THEN 'DEAD_STOCK'
                        WHEN COALESCE((rl.extended_attributes->'stats'->>'views')::int, 0) > 50 
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
                AND COALESCE((rl.extended_attributes->>'inventory')::int, 1) = 1
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
    status_filter: Optional[str] = Query(None, alias="status"),
    sort_by: Optional[str] = Query("detected_at", alias="sort"),
    sort_order: Optional[str] = Query("desc", alias="order")
):
    """
    Report for viewing and filtering unprocessed synchronization events.
    """
    async with get_session() as db:
        # --- 1. Fetch Summary Statistics ---
        summary_query = text("""
        SELECT
            COUNT(*) FILTER (WHERE status = 'pending') AS pending,
            COUNT(*) FILTER (WHERE status = 'processed' AND processed_at >= CURRENT_DATE) AS processed_today,
            COUNT(*) FILTER (WHERE status = 'error') AS errors
        FROM sync_events;
        """)
        summary_result = await db.execute(summary_query)
        summary_stats = dict(summary_result.fetchone()._mapping)

        # --- 2. Fetch Platform Summary ---
        platform_summary_query = text("""
        SELECT platform_name, COUNT(*) as event_count
        FROM sync_events
        GROUP BY platform_name
        ORDER BY event_count DESC;
        """)
        platform_summary_result = await db.execute(platform_summary_query)
        platform_summary = [dict(row._mapping) for row in platform_summary_result.fetchall()]

        # --- 3. Build and Fetch Detailed Events List ---
        params = {}
        where_clauses = []

        if platform_filter:
            where_clauses.append("platform_name = :platform")
            params["platform"] = platform_filter
        if change_type_filter:
            where_clauses.append("change_type = :change_type")
            params["change_type"] = change_type_filter
        if status_filter:
            where_clauses.append("status = :status")
            params["status"] = status_filter
            
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        # **NEW**: Whitelist sortable columns for security
        sortable_columns = {
            "event": "change_type",
            "product": "product_id",
            "detected_at": "detected_at",
            "status": "status"
        }
        sort_column = sortable_columns.get(sort_by, "detected_at")
        sort_direction = "ASC" if sort_order == "asc" else "DESC"

        detailed_query = text(f"""
        SELECT 
            id,
            platform_name,
            product_id,
            external_id,
            change_type,
            change_data,
            status,
            detected_at,
            notes
        FROM sync_events
        WHERE {where_sql}
        ORDER BY {sort_column} {sort_direction}, id DESC
        LIMIT 500;
        """)

        detailed_result = await db.execute(detailed_query, params)
        sync_events = [dict(row._mapping) for row in detailed_result.fetchall()]

    available_platforms = ["reverb", "ebay", "shopify", "vr"]
    available_change_types = [
        "new_listing", "price", "status", "removed_listing", "title", "description"
    ]

    return templates.TemplateResponse("reports/sync_events_report.html", {
        "request": request,
        "sync_events": sync_events,
        "summary_stats": summary_stats,
        "platform_summary": platform_summary,
        "platform_filter": platform_filter,
        "change_type_filter": change_type_filter,
        "status_filter": status_filter,
        "sort_by": sort_by,
        "sort_order": sort_order,
        "platforms": available_platforms,
        "change_types": available_change_types
    })


@router.get("/platform-coverage", response_class=HTMLResponse)
async def platform_coverage_report(request: Request):
    """
    Platform Coverage Report: Identify products missing from certain platforms.
    """
    async with get_session() as db:
        query = text("""
        WITH platform_coverage AS (
            SELECT 
                p.id AS product_id,
                p.sku,
                p.brand,
                p.model,
                p.base_price,
                ARRAY_AGG(pc.platform_name) AS platforms
            FROM products p
            LEFT JOIN platform_common pc ON p.id = pc.product_id
            WHERE pc.status NOT IN ('SOLD', 'ENDED') OR pc.status IS NULL
            GROUP BY p.id, p.sku, p.brand, p.model, p.base_price
        )
        SELECT 
            product_id,
            sku,
            brand,
            model,
            base_price,
            platforms,
            ARRAY(SELECT unnest(ARRAY['shopify', 'ebay', 'reverb', 'vr']) EXCEPT SELECT unnest(platforms)) AS missing_platforms
        FROM platform_coverage
        WHERE ARRAY_LENGTH(platforms, 1) < 4
        ORDER BY ARRAY_LENGTH(missing_platforms, 1) DESC, base_price DESC;
        """)
        
        result = await db.execute(query)
        coverage_data = [dict(row._mapping) for row in result.fetchall()]
        
        return templates.TemplateResponse("reports/platform_coverage.html", {
            "request": request,
            "coverage_data": coverage_data
        })
