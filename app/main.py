# app/main.py

import asyncio
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from fastapi.responses import RedirectResponse
from app.database import get_session
from app.routes import inventory, websockets as websocket_router
from app.core.config import get_settings
from app.core.security import get_current_username

from app import models

from app.routes import shipping, dashboard, reports, health  # matching is now in reports
from app.routes.platforms.ebay import router as ebay_router
from app.routes.platforms.reverb import router as reverb_router
from app.routes.platforms.vr import router as vr_router
from app.routes.platforms.shopify import router as shopify_router
from app.routes.platforms.sync_all import router as sync_all_router
from app.routes.webhooks import router as webhook_router
from app.routes.admin import router as admin_router

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run migrations on startup
    try:
        import subprocess
        import os
        if os.getenv('RUN_MIGRATIONS', 'false').lower() == 'true':
            print("Running database migrations...")
            result = subprocess.run(['alembic', 'upgrade', 'head'], capture_output=True, text=True)
            if result.returncode == 0:
                print("Migrations completed successfully")
                print(result.stdout)
            else:
                print(f"Migration failed: {result.stderr}")
    except Exception as e:
        print(f"Migration error: {e}")
    
    # Startup: Initialize stock manager
    # app.state.stock_manager = await setup_stock_manager()
   # Try to load Dropbox cache at startup
    try:
        from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
        
        print("Loading Dropbox cache at startup...")
        client = AsyncDropboxClient()
        
        # Load cache components
        folder_structure = client.load_folder_structure_from_cache()
        temp_links = client.load_temp_links_from_cache()
        
        if folder_structure and temp_links:
            # Create dropbox_map in app state
            app.state.dropbox_map = {
                'folder_structure': folder_structure,
                'all_entries': [],
                'temp_links': temp_links,
                'scan_stats': {
                    'cached': True,
                    'timestamp': datetime.now().isoformat(),
                    'temporary_links_count': len(temp_links)
                }
            }
            app.state.dropbox_last_updated = datetime.now()
            print(f"Loaded Dropbox cache with {len(temp_links)} temporary links")
    except Exception as e:
        print(f"Error loading Dropbox cache: {str(e)}")
    
    print("Starting periodic Dropbox refresh task...")
    asyncio.create_task(periodic_dropbox_refresh(app))

    # Initialise shared executors
    app.state.vr_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vr-worker")
    try:
        yield  # This is where the app runs
    finally:
        executor = getattr(app.state, "vr_executor", None)
        if executor:
            executor.shutdown(wait=False)

app = FastAPI(
    title="Realtime Inventory Form Flows",
    lifespan=lifespan
)

# Add middleware to handle HTTPS behind proxy
@app.middleware("http")
async def proxy_headers_middleware(request: Request, call_next):
    # Railway sets X-Forwarded-Proto header to indicate HTTPS
    forwarded_proto = request.headers.get("x-forwarded-proto")
    if forwarded_proto == "https":
        # Update the URL scheme to https
        request.scope["scheme"] = "https"
    response = await call_next(request)
    return response

# Templates - define this once at module level
templates = Jinja2Templates(directory="app/templates")

# Mount draft media directory before the broader /static mount so lookups resolve correctly
settings = get_settings()
draft_media_dir = Path(settings.DRAFT_UPLOAD_DIR).expanduser()
draft_media_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static/drafts", StaticFiles(directory=str(draft_media_dir)), name="draft-media")

# Mount static files with proper path resolution
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Add authentication dependency to all routes
from app.core.security import require_auth

# Include routers with authentication
app.include_router(dashboard.router, prefix="", tags=["dashboard"], dependencies=[require_auth()])
app.include_router(inventory.router, prefix="/inventory", tags=["inventory"], dependencies=[require_auth()])
# Import and include inspection router for payload testing
from app.routes import inventory_inspection
app.include_router(inventory_inspection.router, dependencies=[require_auth()])
app.include_router(ebay_router, dependencies=[require_auth()])
app.include_router(reverb_router, dependencies=[require_auth()])
app.include_router(vr_router, dependencies=[require_auth()])
app.include_router(shopify_router, dependencies=[require_auth()])
app.include_router(sync_all_router, dependencies=[require_auth()])
app.include_router(webhook_router)  # Webhooks need to be accessible without auth
app.include_router(websocket_router.router)  # WebSockets handle auth differently
app.include_router(reports.router, prefix="/reports", tags=["reports"], dependencies=[require_auth()])
app.include_router(shipping.router, dependencies=[require_auth()])
# app.include_router(matching.router, prefix="/matching", tags=["matching"], dependencies=[require_auth()])  # Moved to reports
app.include_router(admin_router, dependencies=[require_auth()])
app.include_router(health.router)  # Health check should be accessible without auth

## This will show us in CLI all our registered routes. Uncomment to show.
# print("Registered routes:")
# for route in app.routes:
#     if hasattr(route, 'path') and hasattr(route, 'methods'):
#         print(f"  {route.methods} {route.path}")

# Root redirect - now requires authentication
@app.get("/", dependencies=[Depends(get_current_username)])
async def root():
    return RedirectResponse(url="/inventory")

# Root redirect - this might conflict with dashboard.router if dashboard is also on "/"
# If dashboard.router handles "/", this root redirect might not be hit as dashboard would match first.
# Check the order or ensure dashboard.router is not on the bare "/" if this redirect is desired.
# Your dashboard.router is on prefix="", so its @router.get("/") is indeed the root.
# This @app.get("/") will likely not be reached if dashboard.router handles "/".
# You might want to remove this or make dashboard.router have a prefix if this is the intended root.
# For now, assuming dashboard.router serves your root HTML page.
# @app.get("/")
# async def root():
#     return RedirectResponse(url="/inventory") # Or perhaps "/dashboard" if dashboard.py is the entry?
# Your dashboard.html seems to be served from "/" by dashboard.router


# Test route for 404
@app.get("/test-404")
async def test_404(request: Request):
    """Route to test 404 template"""
    return templates.TemplateResponse(
        "errors/404.html", 
        {"request": request}, 
        status_code=404
    )

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# Debug static files
@app.get("/debug/static")
async def debug_static():
    import os
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    images_dir = os.path.join(static_dir, "images")

    return {
        "static_dir": static_dir,
        "static_exists": os.path.exists(static_dir),
        "images_dir": images_dir,
        "images_exists": os.path.exists(images_dir),
        "background_exists": os.path.exists(os.path.join(images_dir, "background.jpg")),
        "files_in_static": os.listdir(static_dir) if os.path.exists(static_dir) else [],
        "files_in_images": os.listdir(images_dir) if os.path.exists(images_dir) else []
    }


# Database test endpoint
@app.get("/db-test")
async def test_db(session: AsyncSession = Depends(get_session)):
    async with session as session:  # Add this line
        try:
            # Test query
            result = await session.execute(text("SELECT 1"))
            await session.commit()
            return {"status": "database connected"}
        except Exception as e:
            return {"status": "database error", "detail": str(e)}


async def periodic_dropbox_refresh(app):
    """
    Run the Dropbox refresh using the scheduled sync system.
    This now uses intelligent caching and scheduled syncs instead of hourly refreshes.
    """
    from app.services.dropbox.scheduled_sync import DropboxSyncScheduler
    
    # Initialize scheduler
    app.state.dropbox_scheduler = DropboxSyncScheduler(app.state)
    
    # Load initial cached data immediately
    try:
        from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
        from pathlib import Path
        import json
        
        # Load from cache without making API calls
        cache_file = Path("app/cache/dropbox/folder_structure.json")
        links_file = Path("app/cache/dropbox/temp_links.json")
        
        if cache_file.exists():
            with open(cache_file, 'r') as f:
                cache_data = json.load(f)
                # Extract the actual structure from the timestamped cache
                cached_structure = cache_data.get('structure', {}) if isinstance(cache_data, dict) and 'structure' in cache_data else cache_data

            temp_links = {}
            if links_file.exists():
                with open(links_file, 'r') as f:
                    cached_links = json.load(f)
                    # Handle new format where values are dicts with 'full' key
                    for k, v in cached_links.items():
                        if isinstance(v, dict) and 'full' in v:
                            temp_links[k] = v['full']
                        elif isinstance(v, list) and len(v) >= 1:
                            temp_links[k] = v[0]

            app.state.dropbox_map = {
                'folder_structure': cached_structure,
                'temp_links': temp_links,
                'from_cache': True
            }
            app.state.dropbox_last_updated = datetime.fromtimestamp(cache_file.stat().st_mtime)
            print(f"Loaded cached Dropbox data from {app.state.dropbox_last_updated}")
    except Exception as e:
        print(f"Error loading cached Dropbox data: {e}")
    
    # Now run the scheduled sync service
    try:
        await app.state.dropbox_scheduler.run_scheduled_sync()
    except asyncio.CancelledError:
        print("Dropbox sync scheduler cancelled")
    except Exception as e:
        print(f"Error in scheduled sync: {str(e)}")
    finally:
        app.state.dropbox_scan_in_progress = False
            
