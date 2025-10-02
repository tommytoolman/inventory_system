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
            query = text("""
                SELECT reverb_state, COUNT(*) as count 
                FROM reverb_listings 
                GROUP BY reverb_state
                ORDER BY reverb_state
            """)
            result = await self.db.execute(query)
            rows = result.fetchall()
            
            # Initialize counts
            counts = {
                "count": 0,      # live = active
                "sold_count": 0,
                "ended_count": 0,
                "archived_count": 0,
                "draft_count": 0,
                "other_count": 0,
                "total": 0
            }
            
            # Map Reverb states to our categories
            for row in rows:
                state = (row.reverb_state or '').lower()
                count = row.count or 0
                
                if state in ['live', 'active']:
                    counts["count"] += count  # live = active
                elif state == 'sold':
                    counts["sold_count"] += count
                elif state == 'ended':
                    counts["ended_count"] += count
                elif state in ['archived']:
                    counts["archived_count"] += count
                elif state == 'draft':
                    counts["draft_count"] += count
                elif state == 'published':
                    counts["archived_count"] += count
                else:
                    counts["other_count"] += count
            
            # Calculate total
            counts["total"] = sum(counts.values()) - counts["total"]  # Exclude total from sum
            
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
                "total": 0
            }
    
    async def _get_ebay_counts(self) -> dict:
        """Get eBay counts from ebay_listings table with debugging"""
        try:
            # First, let's see what statuses we actually have
            debug_query = text("""
                SELECT listing_status, COUNT(*) as count 
                FROM ebay_listings 
                GROUP BY listing_status 
                ORDER BY count DESC
            """)
            debug_result = await self.db.execute(debug_query)
            debug_rows = debug_result.fetchall()
            
            logger.info(f"eBay listing_status breakdown: {[(row.listing_status, row.count) for row in debug_rows]}")
            
            # Now get organized counts - CASE INSENSITIVE
            active_query = text("""
                SELECT COUNT(*) FROM ebay_listings 
                WHERE LOWER(listing_status) IN ('active')
            """)
            
            sold_query = text("""
                SELECT COUNT(*) FROM ebay_listings 
                WHERE LOWER(listing_status) IN ('sold', 'completed')
            """)
            
            ended_query = text("""
                SELECT COUNT(*) FROM ebay_listings 
                WHERE LOWER(listing_status) IN ('ended', 'unsold', 'cancelled', 'suspended')
            """)
            
            draft_query = text("""
                SELECT COUNT(*) FROM ebay_listings 
                WHERE LOWER(listing_status) IN ('draft', 'scheduled')
            """)
            
            # Check for other statuses
            other_query = text("""
                SELECT COUNT(*) FROM ebay_listings 
                WHERE LOWER(listing_status) NOT IN (
                    'active', 'sold', 'completed', 'ended', 'unsold', 
                    'cancelled', 'suspended', 'draft', 'scheduled'
                ) OR listing_status IS NULL
            """)
            
            active_result = await self.db.execute(active_query)
            sold_result = await self.db.execute(sold_query)
            ended_result = await self.db.execute(ended_query)
            draft_result = await self.db.execute(draft_query)
            other_result = await self.db.execute(other_query)
            
            counts = {
                "count": active_result.scalar() or 0,
                "sold_count": sold_result.scalar() or 0,
                "ended_count": ended_result.scalar() or 0,
                "draft_count": draft_result.scalar() or 0,
                "other_count": other_result.scalar() or 0
            }
            
            # Calculate total
            counts["total"] = sum(counts.values())
            
            logger.info(f"eBay organized counts: {counts}")
            return counts
            
        except Exception as e:
            logger.error(f"Error getting eBay counts: {str(e)}")
            return await self._get_default_platform_counts("ebay")
    
    async def _get_shopify_counts(self) -> dict:
        """Get Shopify counts with proper status breakdown"""
        try:
            # Query to get status breakdown
            query = text("""
                SELECT status, COUNT(*) as count 
                FROM shopify_listings 
                GROUP BY status
                ORDER BY status
            """)
            result = await self.db.execute(query)
            rows = result.fetchall()
            
            # Initialize counts
            counts = {
                "count": 0,      # active
                "sold_count": 0,
                "ended_count": 0,
                "archived_count": 0,
                "draft_count": 0,
                "other_count": 0,
                "total": 0
            }
            
            # Map Shopify statuses to our categories
            for row in rows:
                status = (row.status or '').lower()
                count = row.count or 0
                
                if status == 'active':
                    counts["count"] += count
                elif status == 'sold':
                    counts["sold_count"] += count
                elif status == 'ended':
                    counts["ended_count"] += count
                elif status == 'archived':
                    counts["archived_count"] += count
                elif status == 'draft':
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
                "total": 0
            }
    
    async def _get_vr_counts(self) -> dict:
        """Get Vintage & Rare counts"""
        try:
            query = text("""
                SELECT vr_state, COUNT(*) as count 
                FROM vr_listings 
                GROUP BY vr_state
                ORDER BY vr_state
            """)
            result = await self.db.execute(query)
            rows = result.fetchall()
            
            # Initialize counts
            counts = {
                "count": 0,      # active
                "sold_count": 0,
                "ended_count": 0,
                "archived_count": 0,
                "draft_count": 0,
                "total": 0
            }
            
            # Map V&R states to our categories
            for row in rows:
                state = (row.vr_state or '').lower()
                count = row.count or 0
                
                if state == 'active':
                    counts["count"] += count
                elif state == 'sold':
                    counts["sold_count"] += count
                elif state == 'ended':
                    counts["ended_count"] += count
                elif state == 'draft':
                    counts["draft_count"] += count
                elif state == 'published':
                    counts["archived_count"] += count
            
            # Calculate total
            counts["total"] = sum(counts.values()) - counts["total"]  # Exclude total from sum
            
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
                "total": 0
            }
    
    async def _get_default_platform_counts(self, platform: str) -> dict:
        """Get counts from platform_common table (fallback)"""
        try:
            active_query = select(func.count(PlatformCommon.id)).where(
                PlatformCommon.platform_name == platform,
                func.lower(PlatformCommon.status) == "active"
            )
            sold_query = select(func.count(PlatformCommon.id)).where(
                PlatformCommon.platform_name == platform,
                func.lower(PlatformCommon.status) == "sold"
            )
            other_query = select(func.count(PlatformCommon.id)).where(
                PlatformCommon.platform_name == platform,
                func.lower(PlatformCommon.status).notin_(["active", "sold"])
            )
            
            active_result = await self.db.execute(active_query)
            sold_result = await self.db.execute(sold_query)
            other_result = await self.db.execute(other_query)
            
            counts = {
                "count": active_result.scalar() or 0,
                "sold_count": sold_result.scalar() or 0,
                "other_count": other_result.scalar() or 0
            }
            
            logger.info(f"{platform} (platform_common) counts: {counts}")
            return counts
            
        except Exception as e:
            logger.error(f"Error getting {platform} counts from platform_common: {str(e)}")
            return {"count": 0, "sold_count": 0, "other_count": 0}
    
    async def get_sync_times(self) -> dict:
        """Get last sync times for all platforms"""
        sync_times = {}
        
        for platform in self.platforms:
            try:
                query = select(PlatformCommon.last_sync).where(
                    PlatformCommon.platform_name == platform,
                    PlatformCommon.last_sync.isnot(None)
                ).order_by(PlatformCommon.last_sync.desc()).limit(1)
                
                result = await self.db.execute(query)
                last_sync = result.scalar_one_or_none()
                
                if last_sync:
                    sync_times[f"{platform}_last_sync"] = last_sync
                    
            except Exception as e:
                logger.error(f"Error getting sync time for {platform}: {str(e)}")
        
        return sync_times
    
    async def get_platform_connections(self, request: Request, platform_counts: dict) -> dict:
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
            query = select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(5)
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
                    created_at_local = log.created_at.replace(tzinfo=timezone.utc).astimezone(bst_tz)
                else:
                    created_at_local = log.created_at.astimezone(bst_tz)
                
                activity.append({
                    "icon": icon,
                    "message": message,
                    "time": created_at_local.strftime("%d/%m/%Y, %H:%M:%S")
                })
            
            return activity
            
        except Exception as e:
            logger.error(f"Error getting recent activity: {str(e)}")
            return []
    
    def _get_activity_icon(self, log) -> str:
        """Get icon for activity log entry"""
        if log.details and 'icon' in log.details:
            return log.details['icon']
        
        icon_map = {
            "create": "➕",
            "update": "🔄", 
            "delete": "❌",
            "sync": "✅" if log.details and log.details.get("status") == "success" else "🔄",
            "sync_start": "🔄",
            "sync_error": "⚠️",
            "sale": "💰"
        }
        
        return icon_map.get(log.action, "📝")
    
    def _get_activity_message(self, log) -> str:
        """Get message for activity log entry"""
        if log.details and 'message' in log.details:
            return log.details['message']
        
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
            connections = await service.get_platform_connections(request, platform_counts)
            total_products = await service.get_total_products()
            recent_activity = await service.get_recent_activity()
            
            # System status
            system_status = {
                "background_tasks_healthy": True,
                "last_sync": datetime.now().strftime("%Y-%m-%d %H:%M:%S") if hasattr(request.app.state, "last_sync") else None,
                "total_products": total_products
            }
            
            # Add sync times from app state if available
            for platform in service.platforms:
                if hasattr(request.app.state, f"{platform}_last_sync"):
                    system_status[f"{platform}_last_sync"] = getattr(request.app.state, f"{platform}_last_sync")
            
            # Prepare template context
            context = {
                "request": request,
                **platform_counts,
                **connections,
                **sync_times,
                "shopify_last_sync": sync_times.get("shopify_last_sync", "Never synced"),  # Add default value
                "system_status": system_status,
                "recent_activity": recent_activity,
                "total_products": total_products,
                "debug_platform_counts": platform_counts  # For debugging
            }
            
            logger.info(f"Dashboard context prepared with {len(platform_counts)} platform metrics")
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
                    "error": str(e)
                },
                "recent_activity": [],
                # Set all platform counts to 0
                **{f"{platform}_{key}": 0 
                    for platform in ["ebay", "reverb", "vr", "shopify"] 
                    for key in ["count", "sold_count", "other_count"]},
                **{f"{platform}_connected": False 
                    for platform in ["ebay", "reverb", "vr", "shopify"]},
                # Reverb specific fields
                "reverb_ended_count": 0,
                "reverb_draft_count": 0,
                "reverb_total": 0
            }
            
            return templates.TemplateResponse("dashboard.html", error_context)
