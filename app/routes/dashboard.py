from fastapi import APIRouter, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from datetime import datetime, timezone, timedelta
import logging

# Import the correct database session dependency
from app.database import async_session
from app.core.templates import templates
from app.models.platform_common import PlatformCommon
from app.models.product import Product
from app.models.activity_log import ActivityLog
from app.models.sync_event import SyncEvent

logger = logging.getLogger(__name__)
router = APIRouter()


class DashboardService:
    """Service class to handle dashboard data collection"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.platforms = ["ebay", "reverb", "vr", "shopify"]

    async def get_platform_counts(self) -> dict:
        """Get counts for all platforms"""
        platform_counts = {}

        for platform in self.platforms:
            logger.info(f"Processing platform: {platform}")

            if platform == "reverb":
                counts = await self._get_reverb_counts()
            elif platform == "ebay":
                counts = await self._get_ebay_counts()
            elif platform == "shopify":
                counts = await self._get_shopify_counts()
            elif platform == "vr":
                counts = await self._get_vr_counts()
            else:
                counts = await self._get_default_platform_counts(platform)

            # Add platform-specific counts to main dict
            for key, value in counts.items():
                platform_counts[f"{platform}_{key}"] = value

        return platform_counts

    async def _get_reverb_counts(self) -> dict:
        """Get detailed Reverb counts from reverb_listings table"""
        try:
            query = text(
                """
                SELECT reverb_state, COUNT(*) as count 
                FROM reverb_listings 
                GROUP BY reverb_state
                ORDER BY reverb_state
            """
            )
            result = await self.db.execute(query)
            rows = result.fetchall()

            # Initialize counts
            counts = {
                "count": 0,  # live = active
                "sold_count": 0,
                "ended_count": 0,
                "archived_count": 0,
                "draft_count": 0,
                "other_count": 0,
                "total": 0,
            }

            # Map Reverb states to our categories
            for row in rows:
                state = (row.reverb_state or "").lower()
                count = row.count or 0

                if state in ["live", "active"]:
                    counts["count"] += count  # live = active
                elif state == "sold":
                    counts["sold_count"] += count
                elif state == "ended":
                    counts["ended_count"] += count
                elif state in ["archived"]:
                    counts["archived_count"] += count
                elif state == "draft":
                    counts["draft_count"] += count
                elif state == "published":
                    counts["archived_count"] += count
                else:
                    counts["other_count"] += count

            # Calculate total
            counts["total"] = (
                sum(counts.values()) - counts["total"]
            )  # Exclude total from sum

            logger.info(f"Reverb counts: {counts}")
            return counts

        except Exception as e:
            logger.error(f"Error getting Reverb counts: {str(e)}")
            return {
                "count": 0,
                "sold_count": 0,
                "ended_count": 0,
                "archived_count": 0,
                "draft_count": 0,
                "total": 0,
            }

    async def _get_ebay_counts(self) -> dict:
        """Get eBay counts from ebay_listings table with consistent grouping"""
        try:
            query = text(
                """
                SELECT listing_status, COUNT(*) as count 
                FROM ebay_listings 
                GROUP BY listing_status 
                ORDER BY count DESC
            """
            )
            result = await self.db.execute(query)
            rows = result.fetchall()

            status_category_map = {
                "active": "count",
                "sold": "sold_count",
                "completed": "sold_count",
                "ended": "ended_count",
                "unsold": "ended_count",
                "cancelled": "ended_count",
                "canceled": "ended_count",
                "suspended": "ended_count",
                "archived": "archived_count",
                "draft": "draft_count",
                "scheduled": "draft_count",
            }

            counts = {
                "count": 0,
                "sold_count": 0,
                "ended_count": 0,
                "archived_count": 0,
                "draft_count": 0,
                "other_count": 0,
                "total": 0,
            }

            unknown_statuses = set()

            for row in rows:
                status = (row.listing_status or "").strip().lower()
                count = row.count or 0

                if not status:
                    counts["ended_count"] += count
                    unknown_statuses.add("(empty)")
                    continue

                target_bucket = status_category_map.get(status)
                if target_bucket:
                    counts[target_bucket] += count
                else:
                    counts["other_count"] += count
                    unknown_statuses.add(status)

            counts["total"] = sum(
                value for key, value in counts.items() if key != "total"
            )

            if unknown_statuses:
                logger.info(
                    "eBay counts grouped additional statuses into other_count: %s",
                    sorted(unknown_statuses),
                )

            logger.info(f"eBay organized counts: {counts}")
            return counts

        except Exception as e:
            logger.error(f"Error getting eBay counts: {str(e)}")
            return await self._get_default_platform_counts("ebay")

    async def _get_shopify_counts(self) -> dict:
        """Get Shopify counts with proper status breakdown"""
        try:
            # Query to get status breakdown
            query = text(
                """
                SELECT status, COUNT(*) as count 
                FROM shopify_listings 
                GROUP BY status
                ORDER BY status
            """
            )
            result = await self.db.execute(query)
            rows = result.fetchall()

            # Initialize counts
            counts = {
                "count": 0,  # active
                "sold_count": 0,
                "ended_count": 0,
                "archived_count": 0,
                "draft_count": 0,
                "other_count": 0,
                "total": 0,
            }

            # Map Shopify statuses to our categories
            for row in rows:
                status = (row.status or "").lower()
                count = row.count or 0

                if status == "active":
                    counts["count"] += count
                elif status == "sold":
                    counts["sold_count"] += count
                elif status == "ended":
                    counts["ended_count"] += count
                elif status == "archived":
                    counts["archived_count"] += count
                elif status == "draft":
                    counts["draft_count"] += count
                else:
                    counts["other_count"] += count

            # Calculate total
            counts["total"] = sum(v for k, v in counts.items() if k != "total")

            logger.info(f"Shopify counts: {counts}")
            return counts

        except Exception as e:
            logger.error(f"Error getting Shopify counts: {str(e)}")
            return {
                "count": 0,
                "sold_count": 0,
                "ended_count": 0,
                "archived_count": 0,
                "draft_count": 0,
                "other_count": 0,
                "total": 0,
            }

    async def _get_vr_counts(self) -> dict:
        """Get Vintage & Rare counts"""
        try:
            query = text(
                """
                SELECT vr_state, COUNT(*) as count 
                FROM vr_listings 
                GROUP BY vr_state
                ORDER BY vr_state
            """
            )
            result = await self.db.execute(query)
            rows = result.fetchall()

            # Status categories shared with the VR dashboard card.
            state_category_map = {
                "active": "count",
                "sold": "sold_count",
                "ended": "ended_count",
                "removed": "ended_count",
                "deleted": "ended_count",
                "inactive": "ended_count",
                "archived": "archived_count",
                "published": "archived_count",
                "draft": "draft_count",
                "pending": "draft_count",
            }

            # Initialize counts
            counts = {
                "count": 0,  # active
                "sold_count": 0,
                "ended_count": 0,
                "archived_count": 0,
                "draft_count": 0,
                "other_count": 0,
                "total": 0,
            }

            unknown_states = set()

            # Map V&R states to our categories
            for row in rows:
                state = (row.vr_state or "").lower()
                count = row.count or 0

                target_bucket = state_category_map.get(state)
                if target_bucket:
                    counts[target_bucket] += count
                else:
                    counts["other_count"] += count
                    if state:
                        unknown_states.add(state)

            # Calculate total
            counts["total"] = sum(
                value for key, value in counts.items() if key != "total"
            )

            if unknown_states:
                logger.info(
                    "V&R counts grouped additional states into other_count: %s",
                    sorted(unknown_states),
                )

            logger.info(f"V&R counts: {counts}")
            return counts

        except Exception as e:
            logger.error(f"Error getting V&R counts: {str(e)}")
            return {
                "count": 0,
                "sold_count": 0,
                "ended_count": 0,
                "archived_count": 0,
                "draft_count": 0,
                "other_count": 0,
                "total": 0,
            }

    async def _get_default_platform_counts(self, platform: str) -> dict:
        """Get counts from platform_common table (fallback)"""
        try:
            active_query = select(func.count(PlatformCommon.id)).where(
                PlatformCommon.platform_name == platform,
                func.lower(PlatformCommon.status) == "active",
            )
            sold_query = select(func.count(PlatformCommon.id)).where(
                PlatformCommon.platform_name == platform,
                func.lower(PlatformCommon.status) == "sold",
            )
            other_query = select(func.count(PlatformCommon.id)).where(
                PlatformCommon.platform_name == platform,
                func.lower(PlatformCommon.status).notin_(["active", "sold"]),
            )

            active_result = await self.db.execute(active_query)
            sold_result = await self.db.execute(sold_query)
            other_result = await self.db.execute(other_query)

            counts = {
                "count": active_result.scalar() or 0,
                "sold_count": sold_result.scalar() or 0,
                "other_count": other_result.scalar() or 0,
            }

            logger.info(f"{platform} (platform_common) counts: {counts}")
            return counts

        except Exception as e:
            logger.error(
                f"Error getting {platform} counts from platform_common: {str(e)}"
            )
            return {"count": 0, "sold_count": 0, "other_count": 0}

    async def get_sync_times(self) -> dict:
        """Get last sync times for all platforms"""
        sync_times = {}

        for platform in self.platforms:
            try:
                query = (
                    select(PlatformCommon.last_sync)
                    .where(
                        PlatformCommon.platform_name == platform,
                        PlatformCommon.last_sync.isnot(None),
                    )
                    .order_by(PlatformCommon.last_sync.desc())
                    .limit(1)
                )

                result = await self.db.execute(query)
                last_sync = result.scalar_one_or_none()

                if last_sync:
                    sync_times[f"{platform}_last_sync"] = last_sync

            except Exception as e:
                logger.error(f"Error getting sync time for {platform}: {str(e)}")

        return sync_times

    async def get_sync_statuses(self) -> dict:
        """Get sync status for each platform based on last sync activity.

        Returns 'ok', 'error', or 'stale' for each platform.
        - 'error': Last sync for this platform failed
        - 'stale': No sync in the last 24 hours
        - 'ok': Last sync succeeded
        """
        sync_statuses = {}
        stale_threshold = datetime.now(timezone.utc) - timedelta(hours=24)

        for platform in self.platforms:
            try:
                # Find the most recent sync activity for this platform
                query = (
                    select(ActivityLog)
                    .where(
                        ActivityLog.entity_id == platform,
                        ActivityLog.action.in_(["sync", "sync_error", "sync_start"])
                    )
                    .order_by(ActivityLog.created_at.desc())
                    .limit(1)
                )
                result = await self.db.execute(query)
                last_sync_log = result.scalar_one_or_none()

                if last_sync_log is None:
                    # Never synced
                    sync_statuses[f"{platform}_sync_status"] = "stale"
                elif last_sync_log.action == "sync_error":
                    # Last sync failed
                    sync_statuses[f"{platform}_sync_status"] = "error"
                elif last_sync_log.created_at.replace(tzinfo=timezone.utc) < stale_threshold:
                    # Last sync was more than 24 hours ago
                    sync_statuses[f"{platform}_sync_status"] = "stale"
                else:
                    # Last sync succeeded and is recent
                    sync_statuses[f"{platform}_sync_status"] = "ok"

            except Exception as e:
                logger.error(f"Error getting sync status for {platform}: {str(e)}")
                sync_statuses[f"{platform}_sync_status"] = "ok"  # Default to ok on error

        return sync_statuses

    async def get_platform_connections(
        self, request: Request, platform_counts: dict
    ) -> dict:
        """Determine platform connection status"""
        connections = {}

        for platform in self.platforms:
            # Check app state first, fallback to having active listings
            if hasattr(request.app.state, f"{platform}_connected"):
                is_connected = getattr(request.app.state, f"{platform}_connected")
            else:
                is_connected = platform_counts.get(f"{platform}_count", 0) > 0

            connections[f"{platform}_connected"] = is_connected

        return connections

    async def get_total_products(self) -> int:
        """Get total product count"""
        try:
            query = select(func.count(Product.id))
            result = await self.db.execute(query)
            return result.scalar() or 0
        except Exception as e:
            logger.error(f"Error getting total products: {str(e)}")
            return 0

    async def get_recent_activity(self) -> list:
        """Get recent activity logs"""
        try:
            query = select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(2000)
            result = await self.db.execute(query)
            logs = result.scalars().all()

            bst_tz = timezone(timedelta(hours=1))
            activity = []

            for log in logs:
                # Determine icon
                icon = self._get_activity_icon(log)

                # Determine message
                message = self._get_activity_message(log)

                # Format timestamp
                if log.created_at.tzinfo is None:
                    created_at_local = log.created_at.replace(
                        tzinfo=timezone.utc
                    ).astimezone(bst_tz)
                else:
                    created_at_local = log.created_at.astimezone(bst_tz)

                # Get status from details
                status = "success"
                if log.details:
                    status = log.details.get("status", "success")
                if log.action in ["sync_error", "error"]:
                    status = "error"

                activity.append(
                    {
                        "icon": icon,
                        "message": message,
                        "time": created_at_local.strftime("%d/%m/%Y, %H:%M:%S"),
                        "status": status,
                    }
                )

            return activity

        except Exception as e:
            logger.error(f"Error getting recent activity: {str(e)}")
            return []

    def _get_activity_icon(self, log) -> str:
        """Get icon for activity log entry"""
        if log.details and "icon" in log.details:
            return log.details["icon"]

        icon_map = {
            "create": "➕",
            "update": "🔄",
            "delete": "❌",
            "sync": (
                "✅" if log.details and log.details.get("status") == "success" else "🔄"
            ),
            "sync_start": "🔄",
            "sync_error": "⚠️",
            "sale": "💰",
            "auto_archive": "📦",
            "orders_sync": "📦",
            "stats_refresh": "📊",
        }

        return icon_map.get(log.action, "📝")

    def _get_activity_message(self, log) -> str:
        """Get message for activity log entry"""
        if log.details and "message" in log.details:
            return log.details["message"]

        if log.action == "sync":
            message = f"Synced {log.entity_id}"
            if log.details and "processed" in log.details:
                message += f" ({log.details['processed']} items)"
            return message
        elif log.action == "sync_start":
            return f"Started sync for {log.entity_id}"
        elif log.action == "sync_error":
            message = f"Error syncing {log.entity_id}"
            if log.details and "error" in log.details:
                message += f": {log.details['error'][:30]}..."
            return message
        else:
            message = f"{log.action.capitalize()} {log.entity_type} #{log.entity_id}"
            if log.platform:
                message += f" on {log.platform}"
            return message

    async def get_latest_products(self, limit: int = 5) -> list:
        """Get the most recently added products"""
        try:
            query = text("""
                SELECT id, sku, title, brand, model, base_price, created_at, primary_image, status, is_sold
                FROM products
                ORDER BY created_at DESC
                LIMIT :limit
            """)
            result = await self.db.execute(query, {"limit": limit})
            rows = result.fetchall()

            products = []
            for row in rows:
                # Format created_at
                created_at = row.created_at
                if created_at:
                    time_str = created_at.strftime("%d/%m %H:%M")
                else:
                    time_str = "Unknown"

                # Truncate title if needed
                title = row.title or row.model or "Untitled"
                full_title = title  # Keep full title for tooltip
                if len(title) > 45:
                    title = title[:45] + "..."

                # Determine display status - use status field as source of truth
                raw_status = (row.status or "ACTIVE").upper()
                if raw_status == "SOLD":
                    status = "sold"
                elif raw_status == "DRAFT":
                    status = "draft"
                elif raw_status == "ARCHIVED":
                    status = "archived"
                elif raw_status == "DELETED":
                    status = "deleted"
                else:
                    status = "active"

                products.append({
                    "id": row.id,
                    "sku": row.sku,
                    "title": title,
                    "full_title": full_title,
                    "brand": row.brand or "",
                    "price": row.base_price,
                    "created_at": time_str,
                    "image": row.primary_image,
                    "status": status,
                })

            return products

        except Exception as e:
            logger.error(f"Error getting latest products: {str(e)}")
            return []

    async def get_recent_orders(self, limit: int = 5) -> list:
        """Get the most recent orders across all platforms"""
        try:
            # Query each table separately and combine in Python
            # This avoids complex UNION issues with different column types
            orders = []

            # Reverb orders
            reverb_query = text("""
                SELECT
                    order_number as order_id,
                    title,
                    buyer_name,
                    total_amount as total,
                    created_at,
                    status
                FROM reverb_orders
                ORDER BY created_at DESC
                LIMIT :limit
            """)
            result = await self.db.execute(reverb_query, {"limit": limit})
            for row in result.fetchall():
                orders.append({
                    "platform": "reverb",
                    "order_id": row.order_id,
                    "title": row.title,
                    "buyer": row.buyer_name,
                    "total": row.total,
                    "created_at": row.created_at,
                    "status": row.status,
                })

            # eBay orders
            ebay_query = text("""
                SELECT
                    order_id,
                    raw_payload->'TransactionArray'->'Transaction'->'Item'->>'Title' as title,
                    shipping_name as buyer_name,
                    total_amount as total,
                    created_time as created_at,
                    order_status as status
                FROM ebay_orders
                ORDER BY created_time DESC
                LIMIT :limit
            """)
            result = await self.db.execute(ebay_query, {"limit": limit})
            for row in result.fetchall():
                orders.append({
                    "platform": "ebay",
                    "order_id": row.order_id,
                    "title": row.title or "eBay Order",
                    "buyer": row.buyer_name,
                    "total": row.total,
                    "created_at": row.created_at,
                    "status": row.status,
                })

            # Shopify orders (if any exist)
            shopify_query = text("""
                SELECT
                    order_name as order_id,
                    primary_title as title,
                    CONCAT(customer_first_name, ' ', customer_last_name) as buyer_name,
                    total_amount as total,
                    created_at,
                    financial_status as status
                FROM shopify_orders
                ORDER BY created_at DESC
                LIMIT :limit
            """)
            result = await self.db.execute(shopify_query, {"limit": limit})
            for row in result.fetchall():
                orders.append({
                    "platform": "shopify",
                    "order_id": row.order_id,
                    "title": row.title or "Shopify Order",
                    "buyer": row.buyer_name,
                    "total": row.total,
                    "created_at": row.created_at,
                    "status": row.status,
                })

            # Sort all orders by created_at descending and take top N
            orders.sort(key=lambda x: x["created_at"] or datetime.min, reverse=True)
            orders = orders[:limit]

            # Format for display
            formatted_orders = []
            for order in orders:
                created_at = order["created_at"]
                if created_at:
                    time_str = created_at.strftime("%d/%m %H:%M")
                else:
                    time_str = "Unknown"

                title = order["title"] or "Order"
                full_title = title  # Keep full title for tooltip
                if len(title) > 45:
                    title = title[:45] + "..."

                formatted_orders.append({
                    "platform": order["platform"],
                    "order_id": order["order_id"],
                    "title": title,
                    "full_title": full_title,
                    "buyer": order["buyer"] or "Unknown",
                    "total": order["total"],
                    "created_at": time_str,
                    "status": order["status"] or "Unknown",
                })

            return formatted_orders

        except Exception as e:
            logger.error(f"Error getting recent orders: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return []

    async def get_pending_sync_events(self) -> dict:
        """Get pending sync events with counts by platform and change type"""
        try:
            # Get pending events with product info
            query = text("""
                SELECT
                    se.id,
                    se.platform_name,
                    se.change_type,
                    se.external_id,
                    se.change_data,
                    se.detected_at,
                    se.product_id,
                    p.sku,
                    p.title
                FROM sync_events se
                LEFT JOIN products p ON se.product_id = p.id
                WHERE se.status = 'pending'
                ORDER BY se.detected_at DESC
                LIMIT 50
            """)
            result = await self.db.execute(query)
            rows = result.fetchall()

            # Get counts by platform
            count_query = text("""
                SELECT platform_name, COUNT(*) as count
                FROM sync_events
                WHERE status = 'pending'
                GROUP BY platform_name
            """)
            count_result = await self.db.execute(count_query)
            count_rows = count_result.fetchall()

            platform_counts = {row.platform_name: row.count for row in count_rows}
            total_pending = sum(platform_counts.values())

            # Get counts by change type
            type_query = text("""
                SELECT change_type, COUNT(*) as count
                FROM sync_events
                WHERE status = 'pending'
                GROUP BY change_type
            """)
            type_result = await self.db.execute(type_query)
            type_rows = type_result.fetchall()
            type_counts = {row.change_type: row.count for row in type_rows}

            bst_tz = timezone(timedelta(hours=0))  # UTC for now

            events = []
            for row in rows:
                # Format the change description
                change_data = row.change_data or {}
                if isinstance(change_data, str):
                    import json
                    try:
                        change_data = json.loads(change_data)
                    except:
                        change_data = {}

                change_desc = self._format_change_description(row.change_type, change_data)

                # Format detected time
                detected_at = row.detected_at
                if detected_at:
                    if detected_at.tzinfo is None:
                        detected_at = detected_at.replace(tzinfo=timezone.utc)
                    time_str = detected_at.strftime("%d/%m %H:%M")
                else:
                    time_str = "Unknown"

                events.append({
                    "id": row.id,
                    "platform": row.platform_name,
                    "change_type": row.change_type,
                    "external_id": row.external_id,
                    "change_desc": change_desc,
                    "detected_at": time_str,
                    "product_id": row.product_id,
                    "sku": row.sku,
                    "title": (row.title[:40] + "...") if row.title and len(row.title) > 40 else row.title,
                })

            return {
                "events": events,
                "platform_counts": platform_counts,
                "type_counts": type_counts,
                "total_pending": total_pending,
            }

        except Exception as e:
            logger.error(f"Error getting pending sync events: {str(e)}")
            return {
                "events": [],
                "platform_counts": {},
                "type_counts": {},
                "total_pending": 0,
            }

    def _format_change_description(self, change_type: str, change_data: dict) -> str:
        """Format a human-readable description of the change"""
        if change_type == "status":
            old = change_data.get("old", "?")
            new = change_data.get("new", "?")
            return f"{old} → {new}"
        elif change_type == "price":
            old = change_data.get("old_price", "?")
            new = change_data.get("new_price", "?")
            return f"£{old} → £{new}"
        elif change_type == "quantity":
            old = change_data.get("old_quantity", "?")
            new = change_data.get("new_quantity", "?")
            return f"{old} → {new}"
        elif change_type == "new_listing":
            return "New listing found"
        elif change_type == "removed_listing":
            return "Listing removed"
        elif change_type == "order_sale":
            return "Sale detected"
        else:
            # Fallback - show raw data keys
            return ", ".join(f"{k}: {v}" for k, v in list(change_data.items())[:2])


@router.get("/api/dashboard/latest-products")
async def api_latest_products():
    """AJAX endpoint for latest products"""
    async with async_session() as db:
        service = DashboardService(db)
        products = await service.get_latest_products(limit=5)
        return {"products": products}


@router.get("/api/dashboard/recent-orders")
async def api_recent_orders():
    """AJAX endpoint for recent orders"""
    async with async_session() as db:
        service = DashboardService(db)
        orders = await service.get_recent_orders(limit=5)
        return {"orders": orders}


@router.get("/api/dashboard/pending-sync")
async def api_pending_sync():
    """AJAX endpoint for pending sync events"""
    async with async_session() as db:
        service = DashboardService(db)
        data = await service.get_pending_sync_events()
        return data


@router.get("/")
async def dashboard(request: Request):
    """
    Render the dashboard with key metrics
    """
    async with async_session() as db:
        try:
            service = DashboardService(db)

            # Get all dashboard data
            platform_counts = await service.get_platform_counts()
            sync_times = await service.get_sync_times()
            sync_statuses = await service.get_sync_statuses()
            connections = await service.get_platform_connections(
                request, platform_counts
            )
            total_products = await service.get_total_products()
            recent_activity = await service.get_recent_activity()
            pending_sync_data = await service.get_pending_sync_events()
            latest_products = await service.get_latest_products(limit=5)
            recent_orders = await service.get_recent_orders(limit=5)

            # System status
            system_status = {
                "background_tasks_healthy": True,
                "last_sync": (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    if hasattr(request.app.state, "last_sync")
                    else None
                ),
                "total_products": total_products,
            }

            # Add sync times from app state if available
            for platform in service.platforms:
                if hasattr(request.app.state, f"{platform}_last_sync"):
                    system_status[f"{platform}_last_sync"] = getattr(
                        request.app.state, f"{platform}_last_sync"
                    )

            # Prepare template context
            context = {
                "request": request,
                **platform_counts,
                **connections,
                **sync_times,
                **sync_statuses,
                "shopify_last_sync": sync_times.get(
                    "shopify_last_sync", "Never synced"
                ),  # Add default value
                "system_status": system_status,
                "recent_activity": recent_activity,
                "total_products": total_products,
                "debug_platform_counts": platform_counts,  # For debugging
                # Pending sync events
                "pending_sync_events": pending_sync_data["events"],
                "pending_sync_counts": pending_sync_data["platform_counts"],
                "pending_sync_type_counts": pending_sync_data["type_counts"],
                "total_pending_sync": pending_sync_data["total_pending"],
                # Latest products and orders
                "latest_products": latest_products,
                "recent_orders": recent_orders,
            }

            logger.info(
                f"Dashboard context prepared with {len(platform_counts)} platform metrics"
            )
            return templates.TemplateResponse("dashboard.html", context)

        except Exception as e:
            logger.error(f"Dashboard error: {str(e)}", exc_info=True)

            # Return error dashboard
            error_context = {
                "request": request,
                "error": f"Error loading dashboard data: {str(e)}",
                "system_status": {
                    "background_tasks_healthy": False,
                    "last_sync": None,
                    "total_products": 0,
                    "error": str(e),
                },
                "recent_activity": [],
                # Pending sync events
                "pending_sync_events": [],
                "pending_sync_counts": {},
                "pending_sync_type_counts": {},
                "total_pending_sync": 0,
                # Set all platform counts to 0
                **{
                    f"{platform}_{key}": 0
                    for platform in ["ebay", "reverb", "vr", "shopify"]
                    for key in ["count", "sold_count", "other_count"]
                },
                **{
                    f"{platform}_connected": False
                    for platform in ["ebay", "reverb", "vr", "shopify"]
                },
                **{
                    f"{platform}_sync_status": "error"
                    for platform in ["ebay", "reverb", "vr", "shopify"]
                },
                # Reverb specific fields
                "reverb_ended_count": 0,
                "reverb_draft_count": 0,
                "reverb_total": 0,
                # Latest products and orders
                "latest_products": [],
                "recent_orders": [],
            }

            return templates.TemplateResponse("dashboard.html", error_context)
