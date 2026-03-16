# app/database.py

# type: ignore[misc]
import os
from contextlib import asynccontextmanager

from app.core.config import get_settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

settings = get_settings()

# Use environment variable directly if settings is empty
database_url = settings.DATABASE_URL or os.environ.get("DATABASE_URL", "")
if not database_url:
    raise ValueError("DATABASE_URL is not set in environment variables")

# Convert postgresql:// to postgresql+asyncpg:// for async support
if database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

# Check if using SQLite
is_sqlite = database_url.startswith("sqlite")

# Create engine with conditional parameters
if is_sqlite:
    # SQLite doesn't support pool_size, max_overflow, pool_timeout
    engine = create_async_engine(
        database_url,
        echo=False,
        future=True,
    )
else:
    # PostgreSQL supports pooling
    engine = create_async_engine(
        database_url,
        echo=False,
        future=True,
        pool_size=10,
        max_overflow=20,
        pool_timeout=30,
        pool_recycle=1800,
    )


async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


@asynccontextmanager
async def get_session() -> AsyncSession:
    session = async_session()
    try:
        yield session
    finally:
        await session.close()


@asynccontextmanager
async def get_tenant_session(tenant_id: str) -> AsyncSession:
    """Session with RLS tenant context set.

    Sets the PostgreSQL session variable ``app.current_tenant_id`` so that
    Row-Level Security policies filter rows to the given tenant.  Uses
    ``SET LOCAL`` so the setting is scoped to the current transaction.
    """
    session = async_session()
    try:
        await session.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'"))
        yield session
    finally:
        await session.close()
