# app/services/analytics_service.py
"""
Inventory Analytics Service

Computes velocity benchmarks, category insights, and identifies
actionable opportunities for aged inventory.
"""

from datetime import datetime, date, timedelta
from typing import Optional, Dict, List, Any, Tuple
from sqlalchemy import text, func, case, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
import statistics

from app.models.reverb_historical import ReverbHistoricalListing
from app.models.category_stats import CategoryVelocityStats, InventoryHealthSnapshot
from app.models import Product, ReverbListing, EbayListing, ShopifyListing, VRListing
from app.models.platform_common import PlatformCommon


class InventoryAnalyticsService:
    """
    Service for computing and retrieving inventory analytics.

    Key features:
    - Category velocity benchmarks from historical data
    - Current inventory health analysis
    - Aged inventory identification with recommendations
    - Platform coverage analysis
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # =========================================================================
    # CATEGORY VELOCITY BENCHMARKS
    # =========================================================================

    async def compute_category_benchmarks(self, period_type: str = 'all_time') -> List[Dict]:
        """
        Compute velocity and pricing benchmarks by category from historical data.

        Args:
            period_type: 'all_time', 'last_12m', 'last_6m'

        Returns:
            List of category benchmark dicts
        """
        # Build date filter
        date_filter = "1=1"
        if period_type == 'last_12m':
            cutoff = datetime.now() - timedelta(days=365)
            date_filter = f"sold_at >= '{cutoff.strftime('%Y-%m-%d')}'"
        elif period_type == 'last_6m':
            cutoff = datetime.now() - timedelta(days=180)
            date_filter = f"sold_at >= '{cutoff.strftime('%Y-%m-%d')}'"

        query = text(f"""
            SELECT
                category_root,
                COUNT(*) as total_listed,
                SUM(CASE WHEN outcome = 'sold' THEN 1 ELSE 0 END) as total_sold,
                SUM(CASE WHEN outcome = 'ended' THEN 1 ELSE 0 END) as total_unsold,
                ROUND(100.0 * SUM(CASE WHEN outcome = 'sold' THEN 1 ELSE 0 END) / COUNT(*), 1) as sell_through_rate,
                ROUND(AVG(CASE WHEN outcome = 'sold' THEN days_to_sell END)::numeric, 0) as avg_days_to_sell,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY days_to_sell)
                    FILTER (WHERE outcome = 'sold') as median_days_to_sell,
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY days_to_sell)
                    FILTER (WHERE outcome = 'sold') as p25_days_to_sell,
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY days_to_sell)
                    FILTER (WHERE outcome = 'sold') as p75_days_to_sell,
                ROUND(AVG(final_price)::numeric, 0) as avg_list_price,
                ROUND(AVG(CASE WHEN outcome = 'sold' THEN final_price END)::numeric, 0) as avg_sale_price,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY final_price)
                    FILTER (WHERE outcome = 'sold') as median_sale_price,
                ROUND(AVG(view_count)::numeric, 0) as avg_views,
                ROUND(AVG(watch_count)::numeric, 0) as avg_watches,
                ROUND(AVG(offer_count)::numeric, 1) as avg_offers
            FROM reverb_historical_listings
            WHERE category_root IS NOT NULL
            AND {date_filter}
            GROUP BY category_root
            HAVING COUNT(*) >= 10
            ORDER BY COUNT(*) DESC
        """)

        result = await self.db.execute(query)
        rows = result.fetchall()

        benchmarks = []
        for row in rows:
            benchmarks.append({
                'category': row[0],
                'total_listed': row[1],
                'total_sold': row[2],
                'total_unsold': row[3],
                'sell_through_rate': float(row[4]) if row[4] else 0,
                'avg_days_to_sell': int(row[5]) if row[5] else None,
                'median_days_to_sell': int(row[6]) if row[6] else None,
                'p25_days_to_sell': int(row[7]) if row[7] else None,
                'p75_days_to_sell': int(row[8]) if row[8] else None,
                'avg_list_price': float(row[9]) if row[9] else None,
                'avg_sale_price': float(row[10]) if row[10] else None,
                'median_sale_price': float(row[11]) if row[11] else None,
                'avg_views': int(row[12]) if row[12] else 0,
                'avg_watches': int(row[13]) if row[13] else 0,
                'avg_offers': float(row[14]) if row[14] else 0,
            })

        return benchmarks

    async def get_category_benchmark(self, category: str) -> Optional[Dict]:
        """Get benchmark for a specific category."""
        benchmarks = await self.compute_category_benchmarks()
        for b in benchmarks:
            if b['category'].lower() == category.lower():
                return b
        return None

    # =========================================================================
    # CURRENT INVENTORY ANALYSIS
    # =========================================================================

    async def get_inventory_health_summary(self) -> Dict:
        """
        Get overall health summary of current inventory.
        """
        # Get active products with platform info
        query = text("""
            WITH active_products AS (
                SELECT
                    p.id,
                    p.sku,
                    p.title,
                    p.category,
                    p.base_price,
                    p.created_at,
                    EXTRACT(DAY FROM NOW() - p.created_at)::int as age_days,
                    COUNT(DISTINCT pc.platform_name) as platform_count,
                    array_agg(DISTINCT pc.platform_name) as platforms
                FROM products p
                LEFT JOIN platform_common pc ON pc.product_id = p.id AND pc.status = 'ACTIVE'
                WHERE p.status = 'ACTIVE'
                AND p.quantity > 0
                GROUP BY p.id, p.sku, p.title, p.category, p.base_price, p.created_at
            )
            SELECT
                COUNT(*) as total_items,
                SUM(base_price) as total_value,
                ROUND(AVG(age_days)) as avg_age_days,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY age_days) as median_age_days,
                SUM(CASE WHEN age_days <= 30 THEN 1 ELSE 0 END) as items_0_30d,
                SUM(CASE WHEN age_days > 30 AND age_days <= 90 THEN 1 ELSE 0 END) as items_30_90d,
                SUM(CASE WHEN age_days > 90 AND age_days <= 180 THEN 1 ELSE 0 END) as items_90_180d,
                SUM(CASE WHEN age_days > 180 AND age_days <= 365 THEN 1 ELSE 0 END) as items_180_365d,
                SUM(CASE WHEN age_days > 365 THEN 1 ELSE 0 END) as items_365_plus,
                SUM(CASE WHEN base_price <= 30 THEN base_price ELSE 0 END) as value_0_30d,
                SUM(CASE WHEN age_days > 30 AND age_days <= 90 THEN base_price ELSE 0 END) as value_30_90d,
                SUM(CASE WHEN age_days > 90 AND age_days <= 180 THEN base_price ELSE 0 END) as value_90_180d,
                SUM(CASE WHEN age_days > 180 AND age_days <= 365 THEN base_price ELSE 0 END) as value_180_365d,
                SUM(CASE WHEN age_days > 365 THEN base_price ELSE 0 END) as value_365_plus,
                SUM(CASE WHEN platform_count = 1 THEN 1 ELSE 0 END) as single_platform,
                SUM(CASE WHEN platform_count = 2 THEN 1 ELSE 0 END) as two_platform,
                SUM(CASE WHEN platform_count >= 3 THEN 1 ELSE 0 END) as three_plus_platform
            FROM active_products
        """)

        result = await self.db.execute(query)
        row = result.fetchone()

        if not row or not row[0]:
            return {'error': 'No active inventory found'}

        return {
            'total_items': int(row[0]),
            'total_value': float(row[1]) if row[1] else 0,
            'avg_age_days': int(row[2]) if row[2] else 0,
            'median_age_days': int(row[3]) if row[3] else 0,
            'age_distribution': {
                'counts': {
                    '0-30d': int(row[4] or 0),
                    '30-90d': int(row[5] or 0),
                    '90-180d': int(row[6] or 0),
                    '180-365d': int(row[7] or 0),
                    '365+': int(row[8] or 0),
                },
                'value': {
                    '0-30d': float(row[9] or 0),
                    '30-90d': float(row[10] or 0),
                    '90-180d': float(row[11] or 0),
                    '180-365d': float(row[12] or 0),
                    '365+': float(row[13] or 0),
                }
            },
            'platform_coverage': {
                'single': int(row[14] or 0),
                'two': int(row[15] or 0),
                'three_plus': int(row[16] or 0),
            }
        }

    async def get_aged_inventory(self, min_age_days: int = 90, limit: int = 50) -> List[Dict]:
        """
        Get aged inventory items with recommendations.

        Returns items older than min_age_days with analysis of why they might not be selling.
        """
        query = text("""
            WITH product_stats AS (
                SELECT
                    p.id,
                    p.sku,
                    p.title,
                    p.category,
                    p.base_price,
                    p.created_at,
                    EXTRACT(DAY FROM NOW() - p.created_at)::int as age_days,
                    array_agg(DISTINCT pc.platform_name) FILTER (WHERE pc.status = 'ACTIVE') as platforms,
                    COUNT(DISTINCT pc.platform_name) FILTER (WHERE pc.status = 'ACTIVE') as platform_count
                FROM products p
                LEFT JOIN platform_common pc ON pc.product_id = p.id
                WHERE p.status = 'ACTIVE'
                AND p.quantity > 0
                AND EXTRACT(DAY FROM NOW() - p.created_at) >= :min_age
                GROUP BY p.id
            ),
            reverb_stats AS (
                SELECT
                    lsh.product_id,
                    lsh.view_count as views,
                    lsh.watch_count as watches,
                    0 as offers
                FROM listing_stats_history lsh
                WHERE lsh.recorded_at = (
                    SELECT MAX(recorded_at) FROM listing_stats_history
                )
                AND lsh.platform = 'reverb'
            )
            SELECT
                ps.id,
                ps.sku,
                ps.title,
                ps.category,
                ps.base_price,
                ps.age_days,
                ps.platforms,
                ps.platform_count,
                COALESCE(rs.views, 0) as views,
                COALESCE(rs.watches, 0) as watches,
                COALESCE(rs.offers, 0) as offers
            FROM product_stats ps
            LEFT JOIN reverb_stats rs ON rs.product_id = ps.id
            ORDER BY ps.base_price DESC
            LIMIT :limit
        """)

        result = await self.db.execute(query, {'min_age': min_age_days, 'limit': limit})
        rows = result.fetchall()

        # Get category benchmarks for comparison
        benchmarks = await self.compute_category_benchmarks()
        benchmark_map = {b['category']: b for b in benchmarks}

        items = []
        for row in rows:
            category = row[3]
            price = float(row[4]) if row[4] else 0
            age_days = row[5]
            platforms = row[6] or []
            views = row[8]
            watches = row[9]
            offers = row[10]

            # Get category benchmark
            benchmark = benchmark_map.get(category, {})

            # Analyze issues
            issues = []
            recommendations = []

            # Check platform coverage
            if len(platforms) < 3:
                missing = set(['reverb', 'ebay', 'shopify', 'vr']) - set(platforms or [])
                issues.append(f"Only on {len(platforms)} platform(s)")
                recommendations.append(f"List on: {', '.join(missing)}")

            # Check price vs category benchmark
            if benchmark and benchmark.get('avg_sale_price'):
                avg_price = benchmark['avg_sale_price']
                if price > avg_price * 1.3:
                    issues.append(f"Price {((price/avg_price)-1)*100:.0f}% above category avg")
                    recommendations.append(f"Consider reducing to ~£{avg_price:,.0f}")

            # Check engagement
            if benchmark and age_days > 30:
                expected_views = benchmark.get('avg_views', 100)
                if views < expected_views * 0.5:
                    issues.append("Low engagement (views below benchmark)")
                    recommendations.append("Refresh photos/description")

            # Check age vs category velocity
            if benchmark and benchmark.get('median_days_to_sell'):
                median_days = benchmark['median_days_to_sell']
                if age_days > median_days * 2:
                    issues.append(f"Listed {age_days}d vs category median {median_days}d")

            # Dead stock check
            if views < 10 and watches < 2 and age_days > 60:
                issues.append("Dead stock - minimal engagement")
                recommendations.append("Consider promotional pricing or bundle")

            items.append({
                'id': row[0],
                'sku': row[1],
                'title': row[2],
                'category': category,
                'price': price,
                'age_days': age_days,
                'platforms': platforms,
                'platform_count': row[7],
                'views': views,
                'watches': watches,
                'offers': offers,
                'benchmark': benchmark,
                'issues': issues,
                'recommendations': recommendations,
            })

        return items

    # =========================================================================
    # INSIGHTS DASHBOARD DATA
    # =========================================================================

    async def get_insights_dashboard(self) -> Dict:
        """
        Get all data needed for the Insights dashboard.
        """
        # Get category benchmarks
        benchmarks = await self.compute_category_benchmarks()

        # Get inventory health
        health = await self.get_inventory_health_summary()

        # Get top aged items
        aged_items = await self.get_aged_inventory(min_age_days=90, limit=20)

        # Get quick stats
        quick_stats = await self._get_quick_stats()

        return {
            'category_benchmarks': benchmarks,
            'inventory_health': health,
            'aged_inventory': aged_items,
            'quick_stats': quick_stats,
            'generated_at': datetime.now().isoformat(),
        }

    async def _get_quick_stats(self) -> Dict:
        """Get quick stats for dashboard header."""
        # Historical stats
        hist_query = text("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN outcome = 'sold' THEN 1 ELSE 0 END) as sold,
                ROUND(100.0 * SUM(CASE WHEN outcome = 'sold' THEN 1 ELSE 0 END) / COUNT(*), 1) as overall_str,
                ROUND(AVG(CASE WHEN outcome = 'sold' THEN days_to_sell END)::numeric, 0) as avg_days
            FROM reverb_historical_listings
        """)
        result = await self.db.execute(hist_query)
        hist = result.fetchone()

        # Current inventory
        inv_query = text("""
            SELECT
                COUNT(*) as total,
                SUM(base_price) as total_value,
                ROUND(AVG(EXTRACT(DAY FROM NOW() - created_at))) as avg_age
            FROM products
            WHERE status = 'ACTIVE' AND quantity > 0
        """)
        result = await self.db.execute(inv_query)
        inv = result.fetchone()

        return {
            'historical': {
                'total_listings': int(hist[0]) if hist[0] else 0,
                'total_sold': int(hist[1]) if hist[1] else 0,
                'overall_sell_through': float(hist[2]) if hist[2] else 0,
                'avg_days_to_sell': int(hist[3]) if hist[3] else 0,
            },
            'current': {
                'total_items': int(inv[0]) if inv[0] else 0,
                'total_value': float(inv[1]) if inv[1] else 0,
                'avg_age_days': int(inv[2]) if inv[2] else 0,
            }
        }

    # =========================================================================
    # CATEGORY COMPARISON
    # =========================================================================

    async def compare_item_to_category(self, product_id: int) -> Dict:
        """
        Compare a specific product to its category benchmarks.
        """
        # Get product details
        product_query = text("""
            SELECT
                p.id, p.sku, p.title, p.category, p.base_price,
                EXTRACT(DAY FROM NOW() - p.created_at)::int as age_days
            FROM products p
            WHERE p.id = :product_id
        """)
        result = await self.db.execute(product_query, {'product_id': product_id})
        product = result.fetchone()

        if not product:
            return {'error': 'Product not found'}

        category = product[3]
        benchmark = await self.get_category_benchmark(category)

        if not benchmark:
            return {
                'product': {
                    'id': product[0],
                    'sku': product[1],
                    'title': product[2],
                    'category': category,
                    'price': float(product[4]),
                    'age_days': product[5],
                },
                'benchmark': None,
                'comparison': None
            }

        price = float(product[4])
        age_days = product[5]

        # Calculate comparisons
        price_vs_avg = ((price / benchmark['avg_sale_price']) - 1) * 100 if benchmark.get('avg_sale_price') else None
        age_vs_median = age_days / benchmark['median_days_to_sell'] if benchmark.get('median_days_to_sell') else None

        return {
            'product': {
                'id': product[0],
                'sku': product[1],
                'title': product[2],
                'category': category,
                'price': price,
                'age_days': age_days,
            },
            'benchmark': benchmark,
            'comparison': {
                'price_vs_avg_pct': price_vs_avg,
                'age_vs_median_ratio': age_vs_median,
                'expected_sell_through': benchmark.get('sell_through_rate'),
            }
        }
