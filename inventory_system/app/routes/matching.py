from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional, List, Dict, Any
from app.database import get_session
from app.core.templates import templates
from scripts.product_matcher import ProductMatcher
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/")
async def matching_interface(request: Request):
    """Manual product matching interface"""
    return templates.TemplateResponse("matching/interface.html", {
        "request": request,
        "platforms": ["reverb", "shopify", "vr", "ebay"]
    })

@router.get("/api/stats")
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

@router.get("/api/match-stats")
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
                    'total': int(row.total_products or 0),  # Convert to int
                    'matched': int(row.matched_products or 0),  # Convert to int
                    'unmatched': int(row.unmatched_products or 0),  # Convert to int
                    'percentage': float(row.match_percentage or 0.0)  # Convert to float
                }
            
            return JSONResponse(stats)
            
    except Exception as e:
        logger.error(f"Error getting match stats: {str(e)}")
        # Return fallback data instead of failing
        return JSONResponse({
            "reverb": {"total": 0, "matched": 0, "unmatched": 0, "percentage": 0.0},
            "shopify": {"total": 0, "matched": 0, "unmatched": 0, "percentage": 0.0},
            "vr": {"total": 0, "matched": 0, "unmatched": 0, "percentage": 0.0}
        })

@router.post("/api/products")
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
            
            # PAIR-AWARE MATCH STATUS LOGIC
            if match_status == "unmatched":
                # Check the PAIR of platforms being compared
                if other_platform and set([platform, other_platform]) == set(['reverb', 'shopify']):
                    where_conditions.append("1 = 0")  # Show nothing - they're already matched to each other
                else:
                    # Only exclude products that are specifically matched via product_merges
                    # (Don't exclude multi-platform products unless they're the Reverb+Shopify pair)
                    where_conditions.append("""
                        p.id NOT IN (
                            SELECT DISTINCT kept_product_id FROM product_merges WHERE merged_at IS NOT NULL
                            UNION
                            SELECT DISTINCT merged_product_id FROM product_merges WHERE merged_at IS NOT NULL
                        )
                    """)
                    
            elif match_status == "matched":
                # Check the PAIR of platforms being compared
                if other_platform and set([platform, other_platform]) == set(['reverb', 'shopify']):
                    # No additional filter - show all products (they're matched to each other)
                    pass
                else:
                    # Show only manually matched products
                    where_conditions.append("""
                        (p.id IN (SELECT DISTINCT kept_product_id FROM product_merges WHERE merged_at IS NOT NULL)
                        OR p.id IN (SELECT DISTINCT merged_product_id FROM product_merges WHERE merged_at IS NOT NULL))
                    """)
            
            # Regular filters...
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

@router.post("/api/confirm")
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

@router.get("/api/history")
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

@router.get("/api/filter-options")
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

@router.get("/api/platform-status-options/{platform}")
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


