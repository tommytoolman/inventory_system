"""
Purpose: Handles the initialization and wiring of the StockManager and its associated platform integrations, likely intended to be called during application startup.

Contents:
get_platform_credentials: Helper function to load credentials for different platforms from the application settings 
(using get_settings() from app.core.config) and caches them.
setup_stock_manager: Creates an instance of StockManager, fetches credentials, instantiates concrete platform implementations 
(like EbayPlatform, ReverbPlatform imported from .platforms.*), registers them with the manager, and crucially, starts the StockManager's background 
start_sync_monitor task using asyncio.create_task.
"""


import asyncio
import logging
from typing import Dict
from functools import lru_cache

from app.core.config import get_settings
from app.integrations.stock_manager import StockManager
from app.integrations.events import StockUpdateEvent
from app.integrations.platforms.ebay import EbayPlatform
from app.integrations.platforms.reverb import ReverbPlatform
from app.integrations.platforms.shopify import ShopifyPlatform

logger = logging.getLogger(__name__)

@lru_cache()
def get_platform_credentials() -> Dict[str, Dict[str, str]]:
    """
    Get credentials for all platforms from environment/config
    Cached to avoid repeated environment variable lookups
    """
    settings = get_settings()
    # Filter out None values before returning
    creds = {
        "ebay": {
            "client_id": settings.EBAY_CLIENT_ID,
            "client_secret": settings.EBAY_CLIENT_SECRET,
            # Add other necessary eBay creds if needed by EbayPlatform
        },
        "reverb": {
            "api_key": settings.REVERB_API_KEY,
        },
        "shopify": {
            "shop_url": settings.SHOPIFY_SHOP_URL,
            "api_key": settings.SHOPIFY_API_KEY,
            "password": settings.SHOPIFY_PASSWORD,
        }
    }
    # Return only platforms where essential credentials seem present
    # (Adjust the check based on actual required fields for each platform)
    return {
        p: c for p, c in creds.items()
        if p == "ebay" and c.get("client_id") and c.get("client_secret") # Example check
        or p == "reverb" and c.get("api_key")
        or p == "shopify" and c.get("shop_url") and c.get("api_key") and c.get("password")
    }

async def setup_stock_manager() -> StockManager:
    """
    Initialize and configure the stock manager with all platform integrations
    """
    manager = StockManager()
    credentials = get_platform_credentials()
    
    # Register eBay platform if credentials exist
    if "ebay" in credentials:
        try:
            ebay_platform = EbayPlatform(credentials["ebay"])
            manager.register_platform("ebay", ebay_platform)
            logger.info("Registered eBay Platform Integration")
        except Exception as e:
            logger.error(f"Failed to initialize/register eBay Platform: {e}")
    
    # Register Reverb platform if credentials exist
    if "reverb" in credentials:
        try:
            reverb_platform = ReverbPlatform(credentials["reverb"])
            manager.register_platform("reverb", reverb_platform)
            logger.info("Registered Reverb Platform Integration")
        except Exception as e:
            logger.error(f"Failed to initialize/register Reverb Platform: {e}")

    # Register Shopify platform if credentials exist
    if "shopify" in credentials:
        try:
            shopify_platform = ShopifyPlatform(credentials["shopify"])
            manager.register_platform("shopify", shopify_platform)
            # Log clearly that it's using the placeholder implementation for now
            logger.info("Registered Shopify Platform Integration (Placeholder - Requires Implementation)")
        except Exception as e:
             logger.error(f"Failed to initialize/register Shopify Platform: {e}")
    else:
        logger.info("Shopify credentials not found or incomplete in config, skipping registration.")

    # Register other platforms similarly...

    # Start the sync monitor background task
    logger.info("Starting StockManager sync monitor task...")
    asyncio.create_task(manager.start_sync_monitor())

    return manager