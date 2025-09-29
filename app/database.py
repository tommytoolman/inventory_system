# app/database.py

# type: ignore[misc]
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from contextlib import asynccontextmanager
from app.core.config import get_settings
import os

settings = get_settings()

# Use environment variable directly if settings is empty
database_url = settings.DATABASE_URL or os.environ.get('DATABASE_URL', '')
if not database_url:
    raise ValueError("DATABASE_URL is not set in environment variables")

# Convert postgresql:// to postgresql+asyncpg:// for async support
if database_url.startswith('postgresql://'):
    database_url = database_url.replace('postgresql://', 'postgresql+asyncpg://', 1)

engine = create_async_engine(
    database_url,
    echo=False,
    future=True,
    pool_size=10,             # Add these lines
    max_overflow=20,          # Add these lines
    pool_timeout=30,          # Add these lines
    pool_recycle=1800         # Add these lines
)


async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()

@asynccontextmanager
async def get_session() -> AsyncSession:
    session = async_session()
    try:
        yield session
    finally:
        await session.close()
