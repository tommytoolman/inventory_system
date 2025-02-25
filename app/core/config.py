from pydantic import BaseModel
from functools import lru_cache

class Settings(BaseModel):
    # Database settings
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost/dbname"
    
    # eBay API settings
    EBAY_API_KEY: str = ""
    EBAY_API_SECRET: str = ""
    EBAY_SANDBOX_MODE: bool = True
    
    # File upload settings
    UPLOAD_DIR: str = "app/static/uploads"

@lru_cache()
def get_settings() -> Settings:
    return Settings()