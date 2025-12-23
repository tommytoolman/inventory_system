# app/core/config.py - Consolidated

import os
from functools import lru_cache
from typing import ClassVar, Dict, List, Optional, Any, Annotated
from pydantic import ConfigDict, BeforeValidator
from pydantic_settings import BaseSettings 

def _parse_email_list(value):
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        return [email.strip() for email in value.split(",") if email.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(email).strip() for email in value if str(email).strip()]
    return []


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
    EBAY_SANDBOX_MODE: bool = False # Change to True if in Sandbox test mode
    
    # eBay OAuth
    EBAY_CLIENT_ID: str = ""
    EBAY_DEV_ID: str = ""
    EBAY_CLIENT_SECRET: str = ""
    EBAY_RU_NAME: str = ""
    EBAY_REFRESH_TOKEN: str = ""
    EBAY_TOKEN_USER: str = ""
    EBAY_REFRESH_TOKEN_EXPIRY: str = ""
    EBAY_ENCODED_AUTH_CODE: str = ""
    EBAY_SANDBOX_CLIENT_ID: str = ""
    EBAY_SANDBOX_CLIENT_SECRET: str = ""
    EBAY_SANDBOX_DEV_ID: str = ""
    EBAY_SANDBOX_RU_NAME: str = ""
    EBAY_SANDBOX_ENCODED_AUTH_CODE: str = ""
    EBAY_SANDBOX_REFRESH_TOKEN: str = ""
    EBAY_SANDBOX_TOKEN_USER: str = ""
    EBAY_SANDBOX_REFRESH_TOKEN_EXPIRY: str = ""

    EBAY_USERNAME: str = ""
    EBAY_PASSWORD: str = ""
    EBAY_DEV_USERNAME: str = ""
    EBAY_DEV_PASSWORD: str = ""
    EBAY_SANDBOX_USERNAME: str = ""
    EBAY_SANDBOX_PASSWORD: str = ""
    EBAY_DEV_PASSWORD: str = ""

    # Platform Pricing Markups (percentage over base price)
    SHOPIFY_PRICE_MARKUP_PERCENT: float = 0.0   # Shopify: base price
    EBAY_PRICE_MARKUP_PERCENT: float = 10.0     # eBay: +10% over base
    VR_PRICE_MARKUP_PERCENT: float = 5.0        # V&R: +5% over base
    REVERB_PRICE_MARKUP_PERCENT: float = 5.0    # Reverb: +5% over base

    # Reverb API
    REVERB_API_KEY: str = ""
    REVERB_WEBSITE: str = ""
    REVERB_USERNAME: str = ""
    REVERB_PASSWORD: str = ""
    REVERB_SANDBOX_USERNAME: str = ""
    REVERB_SANDBOX_PASSWORD: str = ""
    REVERB_SANDBOX_API_KEY: str = ""
    
    REVERB_USE_SANDBOX: bool = False
    
    # VintageAndRare
    VINTAGEANDRARE_API_KEY: str = ""
    VINTAGE_AND_RARE_USERNAME: str = ""
    VINTAGE_AND_RARE_PASSWORD: str = ""
    VINTAGE_AND_RARE_WEBSITE: str = ""
    VINTAGE_AND_RARE_COOKIES_FILE: str = ""
    VR_USER_AGENT: str = ""
    SELENIUM_GRID_URL: str = ""
    VR_USE_UDC: bool = False
    VR_HEADLESS: bool = True
    
    # Shopify API (Optional)
    SHOPIFY_SHOP_URL: Optional[str] = None
    SHOPIFY_ONLINE_STORE_PUB_GID: Optional[str] = None
    SHOPIFY_LOCATION_GID: Optional[str] = None
    SHOPIFY_ADMIN_API_ACCESS_TOKEN: Optional[str] = None # Or Admin API Access Token
    SHOPIFY_STOREFRONT_API_ACCESS_TOKEN: Optional[str] = None
    SHOPIFY_API_KEY: Optional[str] = None
    SHOPIFY_API_SECRET: Optional[str] = None
    SHOPIFY_PASSWORD: Optional[str] = None # Specific to Private/Custom Apps
    SHOPIFY_API_VERSION: Optional[str] = None
    
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
    
    # Basic Auth (temporary)
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str
    BASIC_AUTH_USERNAME: Optional[str] = None
    BASIC_AUTH_PASSWORD: Optional[str] = None
    
    # Email notifications
    ADMIN_EMAIL: str = ""
    NOTIFICATION_EMAILS: Annotated[List[str], BeforeValidator(lambda v: _parse_email_list(v))] = []
    ADAM_EMAIL: str = ""
    SIMON_EMAIL: str = ""

    # SMTP / Email
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False
    SMTP_TIMEOUT: int = 30
    SMTP_FROM_EMAIL: Optional[str] = None
    SMTP_FROM_NAME: Optional[str] = None

    # Draft media storage
    DRAFT_UPLOAD_DIR: str = "tmp/draft_uploads"

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
        env_file=os.environ.get('ENV_FILE', '.env') if os.path.exists('.env') else None,
        case_sensitive=True
    )


@lru_cache()
def get_settings():
    """Cached settings to avoid loading .env file for every request"""
    return Settings()

def get_settings_no_cache():
    """Get settings without caching - useful for testing different environments"""
    return Settings()

def clear_settings_cache():
    """Clear the settings cache - useful when switching between environments"""
    get_settings.cache_clear()

def get_test_settings():
    """Get settings specifically for testing - always loads .env.test"""
    import os
    original_env_file = os.environ.get('ENV_FILE')
    os.environ['ENV_FILE'] = '.env.test'
    
    # Clear cache and get fresh settings
    clear_settings_cache()
    settings = Settings()
    
    # Restore original ENV_FILE if it existed
    if original_env_file:
        os.environ['ENV_FILE'] = original_env_file
    elif 'ENV_FILE' in os.environ:
        del os.environ['ENV_FILE']
    
    return settings

def get_test_settings_v2():
    """Get settings specifically for testing - properly loads .env.test"""
    import os
    import importlib
    
    # Set the environment variable
    os.environ['ENV_FILE'] = '.env.test'
    
    # Clear the cache
    clear_settings_cache()
    
    # Force reload the Settings class to pick up new env_file
    from pydantic_settings import BaseSettings
    
    class TestSettings(BaseSettings):
        DATABASE_URL: str = ""
        SECRET_KEY: str = ""
        # Add other essential fields here
        
        model_config = ConfigDict(
            env_file='.env.test',  # Force it to use .env.test
            case_sensitive=True
        )
    
    return TestSettings()

def get_webhook_secret():
    """Get the webhook secret for authentication"""
    return get_settings().WEBSITE_WEBHOOK_SECRET
