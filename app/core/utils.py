"""
Utility functions for the application.
"""
import sqlalchemy

from typing import Type, TypeVar, List, Optional, Dict, Any, Union
from pydantic import BaseModel
from sqlalchemy.orm import Query
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar('T', bound=BaseModel)
M = TypeVar('M')

async def model_to_schema(
    db_model: Any, 
    schema_class: Type[T],
    exclude: List[str] = None
) -> T:
    """
    Convert a SQLAlchemy model instance to a Pydantic schema instance.
    
    Args:
        db_model: SQLAlchemy model instance
        schema_class: Pydantic schema class
        exclude: List of fields to exclude
        
    Returns:
        Instance of the Pydantic schema
    """
    exclude_set = set(exclude) if exclude else set()
    
    return schema_class.model_validate(
        db_model, 
        exclude=exclude_set
    )

async def models_to_schemas(
    db_models: List[Any], 
    schema_class: Type[T],
    exclude: List[str] = None
) -> List[T]:
    """
    Convert a list of SQLAlchemy model instances to a list of Pydantic schema instances.
    
    Args:
        db_models: List of SQLAlchemy model instances
        schema_class: Pydantic schema class
        exclude: List of fields to exclude
        
    Returns:
        List of Pydantic schema instances
    """
    return [await model_to_schema(model, schema_class, exclude) for model in db_models]

async def paginate_query(
    query: Query,
    db: AsyncSession,
    page: int = 1,
    page_size: int = 10
) -> Dict[str, Any]:
    """
    Paginate a SQLAlchemy query.
    
    Args:
        query: SQLAlchemy query object
        db: Database session
        page: Page number (1-indexed)
        page_size: Number of items per page
        
    Returns:
        Dictionary with pagination information and items
    """
    # Get total count for pagination
    count_query = query.statement.with_only_columns([sqlalchemy.func.count()]).order_by(None)
    total = await db.scalar(count_query)
    
    # Apply pagination
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    
    # Execute query
    result = await db.execute(query)
    items = result.scalars().all()
    
    # Calculate pagination values
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1
    has_next = page < total_pages
    has_prev = page > 1
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_next": has_next,
        "has_prev": has_prev
    }