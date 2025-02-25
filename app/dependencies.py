from typing import AsyncGenerator
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.templating import Jinja2Templates

from app.database import async_session

# Initialize templates
templates = Jinja2Templates(directory="app/templates")

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting async database sessions."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()