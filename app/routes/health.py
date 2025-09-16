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
@router.get("/health/migrate")
async def run_migrations():
    """Manually run database migrations"""
    try:
        # Security check - only in production with a secret
        migrate_secret = os.getenv("MIGRATE_SECRET", "")
        if not migrate_secret:
            raise HTTPException(status_code=403, detail="Migration endpoint disabled")
        
        # Get the database URL - keep it as async since alembic/env.py expects async
        db_url = os.environ.get('DATABASE_URL', '')
        if not db_url.startswith('postgresql+asyncpg://'):
            # Ensure it's async format
            db_url = db_url.replace('postgresql://', 'postgresql+asyncpg://', 1)
        
        # Run alembic upgrade with the async URL
        env = os.environ.copy()
        env['DATABASE_URL'] = db_url
        
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            cwd="/app",  # Ensure we're in the app directory
            env=env
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

@router.get("/health/db-audit")
async def database_audit():
    """Comprehensive database audit showing all tables, columns, and types"""
    try:
        from app.database import async_session
        from sqlalchemy import text

        audit_results = {
            "status": "success",
            "tables": {},
            "custom_types": {},
            "alembic_version": None
        }

        async with async_session() as session:
            # Get all tables
            result = await session.execute(text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
            """))
            tables = [row[0] for row in result]

            # For each table, get column information
            for table in tables:
                result = await session.execute(text("""
                    SELECT
                        column_name,
                        data_type,
                        character_maximum_length,
                        is_nullable,
                        column_default
                    FROM information_schema.columns
                    WHERE table_name = :table_name
                    AND table_schema = 'public'
                    ORDER BY ordinal_position
                """), {"table_name": table})

                columns = {}
                for row in result:
                    col_type = row[1]
                    if row[2]:  # has max length
                        col_type += f"({row[2]})"
                    columns[row[0]] = {
                        "type": col_type,
                        "nullable": row[3] == "YES",
                        "default": row[4] if row[4] else None
                    }

                audit_results["tables"][table] = {
                    "columns": columns,
                    "indexes": [],
                    "foreign_keys": []
                }

                # Get indexes
                result = await session.execute(text("""
                    SELECT indexname, indexdef
                    FROM pg_indexes
                    WHERE tablename = :table_name
                    AND schemaname = 'public'
                """), {"table_name": table})

                audit_results["tables"][table]["indexes"] = [
                    {"name": row[0], "definition": row[1]} for row in result
                ]

                # Get foreign keys
                result = await session.execute(text("""
                    SELECT
                        tc.constraint_name,
                        kcu.column_name,
                        ccu.table_name AS foreign_table,
                        ccu.column_name AS foreign_column
                    FROM information_schema.table_constraints AS tc
                    JOIN information_schema.key_column_usage AS kcu
                        ON tc.constraint_name = kcu.constraint_name
                    JOIN information_schema.constraint_column_usage AS ccu
                        ON ccu.constraint_name = tc.constraint_name
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                    AND tc.table_name = :table_name
                """), {"table_name": table})

                audit_results["tables"][table]["foreign_keys"] = [
                    {
                        "name": row[0],
                        "column": row[1],
                        "references": f"{row[2]}.{row[3]}"
                    } for row in result
                ]

            # Get custom types/enums
            result = await session.execute(text("""
                SELECT
                    t.typname AS enum_name,
                    array_agg(e.enumlabel ORDER BY e.enumsortorder) AS enum_values
                FROM pg_type t
                JOIN pg_enum e ON t.oid = e.enumtypid
                JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
                WHERE n.nspname = 'public'
                GROUP BY t.typname
            """))

            for row in result:
                audit_results["custom_types"][row[0]] = list(row[1])

            # Check alembic version
            if 'alembic_version' in tables:
                result = await session.execute(text("SELECT version_num FROM alembic_version"))
                version = result.scalar()
                audit_results["alembic_version"] = version

        return audit_results

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__
        }