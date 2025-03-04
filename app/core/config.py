# app/core/config.py - Consolidated

import os
from functools import lru_cache
from typing import ClassVar, Dict, List, Optional, Any
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
    WEBHOOK_SECRET: str = "your-secret-here"
    
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
    EBAY_CLIENT_ID_SANDBOX: str = ""
    EBAY_CLIENT_SECRET_SANDBOX: str = ""
    EBAY_RU_NAME_SANDBOX: str = "" 
    
    EBAY_USERNAME: str = ""
    EBAY_PASSWORD: str = ""
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
    WEBSITE_API_URL: str = "https://your-website.com/api"
    WEBSITE_USERNAME: str = ""
    WEBSITE_PASSWORD: str = ""
    WEBSITE_WEBHOOK_SECRET: str = "your-secret-here"
    WEBSSITE_URL_OLD: str = ""
    WEBSITE_URL: str = ""
    
    DROPBOX_APP_KEY: str = ""
    DROPBOX_APP_SECRET: str = ""
    DROPBOX_ACCESS_TOKEN: str = ""
    DROPBOX_REFRESH_TOKEN: str = ""
     
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
    
    class Config:
        env_file = ".env"
        case_sensitive = True

@lru_cache()
def get_settings():
    """Cached settings to avoid loading .env file for every request"""
    return Settings()

def get_webhook_secret():
    """Get the webhook secret for authentication"""
    return get_settings().WEBSITE_WEBHOOK_SECRET