from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.database import get_session

router = APIRouter(tags=["health"])

@router.get("/health")
async def health_check():
    """Basic health check"""
    return {"status": "healthy", "service": "RIFF Inventory System"}

@router.get("/health/db")
async def database_health(session: AsyncSession = Depends(get_session)):
    """Check database connectivity and tables"""
    try:
        # Check connection
        result = await session.execute(text("SELECT 1"))
        
        # Check if products table exists
        tables_result = await session.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        )
        tables = [row[0] for row in tables_result]
        
        return {
            "status": "healthy",
            "database": "connected",
            "tables_count": len(tables),
            "tables": tables[:10]  # Show first 10 tables
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "database": "error",
            "error": str(e)
        }