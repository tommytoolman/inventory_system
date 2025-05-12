from fastapi import APIRouter, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from datetime import datetime

# Import the correct database session dependency
from app.database import async_session
from app.core.templates import templates
from app.models.platform_common import PlatformCommon
from app.models.product import Product

router = APIRouter()

@router.get("/")
async def dashboard(request: Request):
    """
    Render the dashboard/splash page with key metrics
    """
    # Get platform counts
    platform_counts = {}
    platforms = ["ebay", "reverb", "vr", "website"]
    
    # Create a new session using async_session()
    async with async_session() as db:
        try:
            # Get counts for all platforms with status breakdown
            for platform in platforms:
                try:
                    # Get active listings
                    active_query = select(func.count(PlatformCommon.id)).where(
                        PlatformCommon.platform_name == platform.upper(),
                        PlatformCommon.status == "ACTIVE"
                    )
                    active_result = await db.execute(active_query)
                    active_count = active_result.scalar() or 0
                    
                    # Get sold listings
                    sold_query = select(func.count(PlatformCommon.id)).where(
                        PlatformCommon.platform_name == platform.upper(),
                        PlatformCommon.status == "SOLD"
                    )
                    sold_result = await db.execute(sold_query)
                    sold_count = sold_result.scalar() or 0
                    
                    # Get other listings (like DRAFT, ARCHIVED, etc.)
                    other_query = select(func.count(PlatformCommon.id)).where(
                        PlatformCommon.platform_name == platform.upper(),
                        PlatformCommon.status.notin_(["ACTIVE", "SOLD"])
                    )
                    other_result = await db.execute(other_query)
                    other_count = other_result.scalar() or 0
                    
                    # Store all counts
                    platform_counts[f"{platform}_count"] = active_count
                    platform_counts[f"{platform}_sold_count"] = sold_count
                    platform_counts[f"{platform}_other_count"] = other_count
                    
                    # Check if we need to fall back to platform-specific tables
                    if active_count == 0 and sold_count == 0 and other_count == 0:
                        if platform == "ebay":
                            # Try the ebay_listings table if it exists
                            try:
                                # For active listings
                                ebay_active_query = select(func.count(text("id"))).select_from(text("ebay_listings")) \
                                    .where(text("listing_status = 'ACTIVE'"))
                                ebay_active_result = await db.execute(ebay_active_query)
                                active_count = ebay_active_result.scalar() or 0
                                
                                # For sold listings
                                ebay_sold_query = select(func.count(text("id"))).select_from(text("ebay_listings")) \
                                    .where(text("listing_status = 'SOLD'"))
                                ebay_sold_result = await db.execute(ebay_sold_query)
                                sold_count = ebay_sold_result.scalar() or 0
                                
                                # For other listings
                                ebay_other_query = select(func.count(text("id"))).select_from(text("ebay_listings")) \
                                    .where(text("listing_status NOT IN ('ACTIVE', 'SOLD')"))
                                ebay_other_result = await db.execute(ebay_other_query)
                                other_count = ebay_other_result.scalar() or 0
                                
                                platform_counts[f"{platform}_count"] = active_count
                                platform_counts[f"{platform}_sold_count"] = sold_count
                                platform_counts[f"{platform}_other_count"] = other_count
                            except Exception as e:
                                print(f"Error querying ebay_listings: {str(e)}")
                                # Table might not exist
                                pass
                        
                        elif platform == "reverb":
                            # Try the reverb_listings table if it exists
                            try:
                                # For active listings
                                reverb_active_query = select(func.count(text("id"))).select_from(text("reverb_listings")) \
                                    .where(text("reverb_state = 'published'"))
                                reverb_active_result = await db.execute(reverb_active_query)
                                active_count = reverb_active_result.scalar() or 0
                                
                                # For sold listings
                                reverb_sold_query = select(func.count(text("id"))).select_from(text("reverb_listings")) \
                                    .where(text("reverb_state = 'sold'"))
                                reverb_sold_result = await db.execute(reverb_sold_query)
                                sold_count = reverb_sold_result.scalar() or 0
                                
                                # For other listings
                                reverb_other_query = select(func.count(text("id"))).select_from(text("reverb_listings")) \
                                    .where(text("reverb_state NOT IN ('published', 'sold')"))
                                reverb_other_result = await db.execute(reverb_other_query)
                                other_count = reverb_other_result.scalar() or 0
                                
                                platform_counts[f"{platform}_count"] = active_count
                                platform_counts[f"{platform}_sold_count"] = sold_count
                                platform_counts[f"{platform}_other_count"] = other_count
                            except Exception as e:
                                print(f"Error querying reverb_listings: {str(e)}")
                                # Table might not exist
                                pass
                        
                        elif platform == "vr":
                            # Try the vr_listings table if it exists
                            try:
                                vr_query = select(func.count(text("id"))).select_from(text("vr_listings"))
                                vr_result = await db.execute(vr_query)
                                count = vr_result.scalar() or 0
                                
                                # Set only active count for now, as VR doesn't track status separately
                                platform_counts[f"{platform}_count"] = count
                                platform_counts[f"{platform}_sold_count"] = 0
                                platform_counts[f"{platform}_other_count"] = 0
                            except Exception as e:
                                print(f"Error querying vr_listings: {str(e)}")
                                # Table might not exist
                                pass
                        
                        elif platform == "website":
                            # Try the website_listings table if it exists
                            try:
                                website_query = select(func.count(text("id"))).select_from(text("website_listings"))
                                website_result = await db.execute(website_query)
                                count = website_result.scalar() or 0
                                
                                # Set only active count for now
                                platform_counts[f"{platform}_count"] = count
                                platform_counts[f"{platform}_sold_count"] = 0
                                platform_counts[f"{platform}_other_count"] = 0
                            except Exception as e:
                                print(f"Error querying website_listings: {str(e)}")
                                # Table might not exist
                                pass
                            
                except Exception as e:
                    print(f"Error getting count for {platform}: {str(e)}")
                    platform_counts[f"{platform}_count"] = 0
                    platform_counts[f"{platform}_sold_count"] = 0
                    platform_counts[f"{platform}_other_count"] = 0
            
            # Get total product count
            product_query = select(func.count(Product.id))
            product_result = await db.execute(product_query)
            total_products = product_result.scalar() or 0
            
            # Get platform connection status - using app state if available
            platform_connections = {}
            for platform in platforms:
                # Check if we have a state variable for platform connection
                # Fallback to checking if we have any items
                is_connected = False
                
                if hasattr(request.app.state, f"{platform}_connected"):
                    is_connected = getattr(request.app.state, f"{platform}_connected")
                else:
                    is_connected = platform_counts[f"{platform}_count"] > 0
                    
                platform_connections[f"{platform}_connected"] = is_connected
            
            # Get recent activity from database (last 5 changes), if table exists
            recent_activity = []
            try:
                # If you have an activity_log table
                activity_query = text("""
                    SELECT action, entity_type, entity_id, created_at 
                    FROM activity_log
                    ORDER BY created_at DESC
                    LIMIT 5
                """)
                activity_result = await db.execute(activity_query)
                activity_rows = activity_result.fetchall()
                
                for row in activity_rows:
                    icon = "📝"  # Default icon
                    if row.action == "create":
                        icon = "➕"
                    elif row.action == "update":
                        icon = "🔄"
                    elif row.action == "delete":
                        icon = "❌"
                    elif row.action == "sync":
                        icon = "🔄"
                    
                    recent_activity.append({
                        "icon": icon,
                        "message": f"{row.action.capitalize()} {row.entity_type} #{row.entity_id}",
                        "time": row.created_at.strftime("%Y-%m-%d %H:%M")
                    })
            except Exception as e:
                # If activity_log doesn't exist or other error
                print(f"Error fetching activity log: {e}")
            
            # System status
            system_status = {
                "background_tasks_healthy": True,
                "last_sync": datetime.now().strftime("%Y-%m-%d %H:%M:%S") if hasattr(request.app.state, "last_sync") else None,
                "total_products": total_products
            }
            
            # Add sync times if available in app state
            for platform in platforms:
                if hasattr(request.app.state, f"{platform}_last_sync"):
                    system_status[f"{platform}_last_sync"] = getattr(request.app.state, f"{platform}_last_sync")
            
            # Return template with data
            return templates.TemplateResponse(
                "dashboard.html", 
                {
                    "request": request,
                    **platform_counts,
                    **platform_connections,
                    "system_status": system_status,
                    "recent_activity": recent_activity,
                    "total_products": total_products
                }
            )
        
        except Exception as e:
            # Important: Roll back the transaction if any error occurs
            await db.rollback()
            print(f"Dashboard error: {str(e)}")
            
            # Return a minimal dashboard with error information
            return templates.TemplateResponse(
                "dashboard.html",
                {
                    "request": request,
                    "ebay_count": 0,
                    "reverb_count": 0,
                    "vr_count": 0,
                    "website_count": 0,
                    "ebay_sold_count": 0,
                    "reverb_sold_count": 0,
                    "vr_sold_count": 0,
                    "website_sold_count": 0,
                    "ebay_other_count": 0,
                    "reverb_other_count": 0,
                    "vr_other_count": 0,
                    "website_other_count": 0,
                    "ebay_connected": False,
                    "reverb_connected": False,
                    "vr_connected": False,
                    "website_connected": False,
                    "system_status": {
                        "background_tasks_healthy": False,
                        "last_sync": None,
                        "total_products": 0,
                        "error": str(e)
                    },
                    "recent_activity": [],
                    "error": f"Error loading dashboard data: {str(e)}"
                }
            )