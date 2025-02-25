# app/config.py
import logging.config
from typing import ClassVar
from pydantic_settings import BaseSettings
from functools import lru_cache
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    # Database settings
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost/inventory"
    
    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    
    # Platform APIs
    EBAY_API_KEY: str = ""
    EBAY_API_SECRET: str = ""
    EBAY_CLIENT_ID: str = ""
    EBAY_CLIENT_SECRET: str = ""
    EBAY_RU_NAME: str = ""
    EBAY_ENCODED_AUTH_CODE: str = ""
    EBAY_REFRESH_TOKEN: str = ""
    EBAY_CLIENT_ID_SANDBOX: str = ""
    EBAY_CLIENT_SECRET_SANDBOX: str = ""
    EBAY_RU_NAME_SANDBOX: str = ""
    EBAY_USERNAME: str = ""
    EBAY_PASSWORD: str = ""
    EBAY_DEV_PASSWORD: str = ""

    REVERB_API_KEY: str = ""
    REVERB_WEBSITE: str = ""
    REVERB_USERNAME: str = ""
    REVERB_PASSWORD: str = ""

    VINTAGEANDRARE_API_KEY: str = ""
    VINTAGE_AND_RARE_WEBSITE: str = ""
    VINTAGE_AND_RARE_USERNAME: str = ""
    VINTAGE_AND_RARE_PASSWORD: str = ""

    WEBSITE_API_KEY: str = ""
    WEBSSITE_URL_OLD: str = ""
    WEBSITE_URL: str = ""
    WEBSITE_USERNAME: str = ""
    WEBSITE_PASSWORD: str = ""

    ADAM_EMAIL: str = ""
    SIMON_EMAIL: str = ""
    
    # Monitoring
    SENTRY_DSN: str = ""

    # Environment
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = True

    WEBSITE_WEBHOOK_SECRET: str = 'your-secret-here'
    WEBSITE_API_URL: ClassVar = "https://your-website.com/api"

def get_webhook_secret():
    return Settings.WEBSITE_WEBHOOK_SECRET

@lru_cache()
def get_settings():
    return Settings()