from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.database import get_session
import subprocess
import os

router = APIRouter(tags=["health"])

@router.get("/health")
async def health_check():
    """Basic health check"""
    return {"status": "healthy", "service": "RIFF Inventory System"}

@router.get("/health/db")
async def database_health():
    """Check database connectivity and tables"""
    try:
        from app.database import async_session
        
        async with async_session() as session:
            # Check connection
            result = await session.execute(text("SELECT 1"))
            
            # Check if products table exists
            tables_result = await session.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name")
            )
            tables = [row[0] for row in tables_result]
            
            return {
                "status": "healthy",
                "database": "connected",
                "tables_count": len(tables),
                "tables": tables
            }
    except Exception as e:
        return {
            "status": "unhealthy",
            "database": "error",
            "error": str(e)
        }

@router.post("/health/migrate")
async def run_migrations():
    """Manually run database migrations"""
    try:
        # Security check - only in production with a secret
        migrate_secret = os.getenv("MIGRATE_SECRET", "")
        if not migrate_secret:
            raise HTTPException(status_code=403, detail="Migration endpoint disabled")
        
        # Run alembic upgrade
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            cwd="/app"  # Ensure we're in the app directory
        )
        
        if result.returncode == 0:
            # Check tables after migration
            from app.database import async_session
            async with async_session() as session:
                tables_result = await session.execute(
                    text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name")
                )
                tables = [row[0] for row in tables_result]
            
            return {
                "status": "success",
                "message": "Migrations completed",
                "output": result.stdout,
                "tables_created": len(tables),
                "tables": tables
            }
        else:
            return {
                "status": "error",
                "message": "Migration failed",
                "error": result.stderr,
                "output": result.stdout
            }
    except Exception as e:
        return {
            "status": "error",
            "message": "Migration exception",
            "error": str(e)
        }