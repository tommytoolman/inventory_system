from typing import Dict
import asyncio
from functools import lru_cache

from app.core.config import get_settings  # Assuming you have a config module
from app.integrations.stock_manager import StockManager
from app.integrations.events import StockUpdateEvent
from app.integrations.platforms.ebay import EbayPlatform
from app.integrations.platforms.reverb import ReverbPlatform
# Import other platforms as needed

@lru_cache()
def get_platform_credentials() -> Dict[str, Dict[str, str]]:
    """
    Get credentials for all platforms from environment/config
    Cached to avoid repeated environment variable lookups
    """
    settings = get_settings()
    return {
        "ebay": {
            "client_id": settings.EBAY_CLIENT_ID,
            "client_secret": settings.EBAY_CLIENT_SECRET,
        },
        "reverb": {
            "api_key": settings.REVERB_API_KEY,
        },
        # Add other platform credentials as needed
    }

async def setup_stock_manager() -> StockManager:
    """
    Initialize and configure the stock manager with all platform integrations
    """
    manager = StockManager()
    credentials = get_platform_credentials()
    
    # Register eBay platform if credentials exist
    if "ebay" in credentials:
        ebay_platform = EbayPlatform(credentials["ebay"])
        manager.register_platform("ebay", ebay_platform)
    
    # Register Reverb platform if credentials exist
    if "reverb" in credentials:
        reverb_platform = ReverbPlatform(credentials["reverb"])
        manager.register_platform("reverb", reverb_platform)
    
    # Start the sync monitor
    asyncio.create_task(manager.start_sync_monitor())
    
    return manager