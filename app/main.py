# app/main.py

import asyncio
from datetime import datetime, timedelta

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
from app.routes.platforms.reverb import router as reverb_router
from app.routes.webhooks import router as webhook_router
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize stock manager
    app.state.stock_manager = await setup_stock_manager()
    yield
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
app.include_router(inventory.router, prefix="/inventory", tags=["inventory"])
app.include_router(reverb_router)
app.include_router(webhook_router)

# @app.on_event("startup")
# async def startup_event():
#     # Initialize stock manager
#     app.state.stock_manager = await setup_stock_manager()

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
@app.on_event("startup")
async def start_background_tasks():
    asyncio.create_task(periodic_dropbox_refresh(app))

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
            
