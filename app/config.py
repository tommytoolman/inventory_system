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
    REVERB_API_KEY: str = ""
    VINTAGEANDRARE_API_KEY: str = ""
    WEBSITE_API_KEY: str = ""
    
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