# app/main.py

import asyncio
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from fastapi.responses import RedirectResponse
from .database import get_session
from app.routes import inventory
from app.core.config import get_settings

from app import models

from app.integrations.setup import setup_stock_manager
from app.integrations.stock_manager import StockManager
from app.integrations.platforms.ebay import EbayPlatform
from app.integrations.platforms.reverb import ReverbPlatform
from app.routes import shipping, dashboard
from app.routes.platforms.reverb import router as reverb_router
from app.routes.platforms.vr import router as vr_router
from app.routes.webhooks import router as webhook_router
from contextlib import asynccontextmanager




@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize stock manager
    app.state.stock_manager = await setup_stock_manager()
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
    
    yield  # This is where the app runs
    # Shutdown: No specific cleanup needed in this case

app = FastAPI(
    title="Realtime Inventory Form Flows",
    lifespan=lifespan
)

# Templates - define this once at module level
templates = Jinja2Templates(directory="app/templates")

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Include routers
app.include_router(dashboard.router, prefix="", tags=["dashboard"])
app.include_router(inventory.router, prefix="/inventory", tags=["inventory"])
app.include_router(reverb_router)
app.include_router(vr_router)
app.include_router(webhook_router)
app.include_router(shipping.router)

# Root redirect
@app.get("/")
async def root():
    return RedirectResponse(url="/inventory")

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
        
# In main.py or app setup
# @app.on_event("startup")
# async def start_background_tasks():
#     asyncio.create_task(periodic_dropbox_refresh(app))

# In app/main.py
# @app.on_event("startup")
# async def start_background_tasks():
#     # Existing code...
    
#     # Try to load Dropbox cache
#     try:
#         from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
        
#         print("Loading Dropbox cache at startup...")
#         client = AsyncDropboxClient()
        
#         # Load cache components
#         folder_structure = client.load_folder_structure_from_cache()
#         temp_links = client.load_temp_links_from_cache()
        
#         if folder_structure and temp_links:
#             # Create a dropbox_map in app state
#             app.state.dropbox_map = {
#                 'folder_structure': folder_structure,
#                 'all_entries': [],
#                 'temp_links': temp_links
#             }
#             app.state.dropbox_last_updated = datetime.now()
#             print(f"Loaded Dropbox cache with {len(temp_links)} temporary links")
#     except Exception as e:
#         print(f"Error loading Dropbox cache: {str(e)}")

async def periodic_dropbox_refresh(app):
    """Run the Dropbox refresh periodically"""
    while True:
        # Wait first to avoid running during startup
        await asyncio.sleep(3600)  # 1 hour
        
        # Don't refresh if scan already in progress
        if hasattr(app.state, 'dropbox_scan_in_progress') and app.state.dropbox_scan_in_progress:
            continue
        
        try:
            # Check if we should refresh (if older than 1 hour)
            if (hasattr(app.state, 'dropbox_last_updated') and 
                (datetime.now() - app.state.dropbox_last_updated > timedelta(hours=1))):
                
                print("Starting scheduled Dropbox refresh")
                from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
                
                # Mark as in progress
                app.state.dropbox_scan_in_progress = True
                app.state.dropbox_scan_progress = {'status': 'refreshing', 'progress': 0}
                
                # Perform refresh
                client = AsyncDropboxClient(app.state.settings.DROPBOX_ACCESS_TOKEN)
                dropbox_map = await client.scan_and_map_folder()
                
                # Update app state
                app.state.dropbox_map = dropbox_map
                app.state.dropbox_last_updated = datetime.now()
        except Exception as e:
            print(f"Error in scheduled refresh: {str(e)}")
        finally:
            app.state.dropbox_scan_in_progress = False
            
