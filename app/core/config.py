# app/core/config.py - Consolidated

import os
from functools import lru_cache
from typing import ClassVar, Dict, List, Optional, Any
from pydantic import ConfigDict
from pydantic_settings import BaseSettings 

class Settings(BaseSettings):
    """
    Application settings.
    Loads values from environment variables (.env file)
    """
    # Database settings
    DATABASE_URL: str = ""
    
    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    WEBHOOK_SECRET: str = ""
    
    # eBay API
    EBAY_API_KEY: str = ""
    EBAY_API_SECRET: str = ""
    EBAY_SANDBOX_MODE: bool = True
    
    # eBay OAuth
    EBAY_CLIENT_ID: str = ""
    EBAY_DEV_ID: str = ""
    EBAY_CLIENT_SECRET: str = ""
    EBAY_RU_NAME: str = ""
    EBAY_REFRESH_TOKEN: str = ""
    EBAY_ENCODED_AUTH_CODE: str = ""
    EBAY_SANDBOX_CLIENT_ID: str = ""
    EBAY_SANDBOX_CLIENT_SECRET: str = ""
    EBAY_SANDBOX_DEV_ID: str = ""
    EBAY_SANDBOX_RU_NAME: str = ""
    EBAY_SANDBOX_ENCODED_AUTH_CODE: str = ""
    EBAY_SANDBOX_REFRESH_TOKEN: str = ""
    
    EBAY_USERNAME: str = ""
    EBAY_PASSWORD: str = ""
    EBAY_DEV_USERNAME: str = ""
    EBAY_DEV_PASSWORD: str = ""
    EBAY_SANDBOX_USERNAME: str = ""
    EBAY_SANDBOX_PASSWORD: str = ""
    EBAY_DEV_PASSWORD: str = ""

    
    # Reverb API
    REVERB_API_KEY: str = ""
    REVERB_WEBSITE: str = ""
    REVERB_USERNAME: str = ""
    REVERB_PASSWORD: str = ""
    REVERB_SANDBOX_USERNAME: str = ""
    REVERB_SANDBOX_PASSWORD: str = ""
    
    # VintageAndRare
    VINTAGEANDRARE_API_KEY: str = ""
    VINTAGE_AND_RARE_USERNAME: str = ""
    VINTAGE_AND_RARE_PASSWORD: str = ""
    VINTAGE_AND_RARE_WEBSITE: str = ""
    
    # Website API
    WEBSITE_API_KEY: str = ""
    WEBSITE_API_URL: str = ""
    WEBSITE_USERNAME: str = ""
    WEBSITE_PASSWORD: str = ""
    WEBSITE_WEBHOOK_SECRET: str = ""
    WEBSSITE_URL_OLD: str = ""
    WEBSITE_URL: str = ""
    
    # Shopify API (Optional)
    SHOPIFY_SHOP_URL: Optional[str] = None
    SHOPIFY_API_KEY: Optional[str] = None # Or Admin API Access Token
    SHOPIFY_PASSWORD: Optional[str] = None # Specific to Private/Custom Apps
    
    
    DROPBOX_APP_KEY: str = ""
    DROPBOX_APP_SECRET: str = ""
    DROPBOX_ACCESS_TOKEN: str = ""
    DROPBOX_REFRESH_TOKEN: str = ""
        
    TINYMCE_API_KEY: str = "" 
     
    # File paths
    UPLOAD_DIR: str = "app/static/uploads"
    
    # Monitoring
    SENTRY_DSN: str = ""
    
    # Environment
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    
    # Email notifications
    ADMIN_EMAIL: str = ""
    NOTIFICATION_EMAILS: List[str] = []
    ADAM_EMAIL: str = ""
    SIMON_EMAIL: str = ""
    
    # DHL Express settings
    
    DHL_API_KEY: str = ""
    DHL_API_SECRET: str = ""
    DHL_ACCOUNT_NUMBER: str = ""
    DHL_TEST_MODE: bool = True
    DHL_EMAIL: str = ""
    DHL_PWD: str = ""
    DHL_DEV_EMAIL: str = ""
    DHL_DEV_PWD: str = ""
    
    TNT_EMAIL: str = ""
    TNT_PWD: str = ""

    FDX_USERNAME: str = ""
    FDX_PWD: str = ""
    
    model_config = ConfigDict(
        env_file = ".env",
        case_sensitive = True
    )

@lru_cache()
def get_settings():
    """Cached settings to avoid loading .env file for every request"""
    return Settings()

def get_webhook_secret():
    """Get the webhook secret for authentication"""
    return get_settings().WEBSITE_WEBHOOK_SECRET

# Think this is redudant
# def get_settings():
#     return Settings()