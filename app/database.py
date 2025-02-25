# app/database.py

# type: ignore[misc]
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.ext.declarative import declarative_base
from contextlib import asynccontextmanager
from .config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,  # Removed settings dependency
    future=True
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