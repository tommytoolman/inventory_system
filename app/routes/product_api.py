"""
API routes for product management with updated model-schema separation.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.dependencies import get_db
from app.schemas.product import ProductCreate, ProductRead, ProductUpdate
from app.services.product_service import ProductService
from app.core.exceptions import ProductCreationError, ProductNotFoundError

router = APIRouter(prefix="/api/products", tags=["products"])

@router.post("/", response_model=ProductRead)
async def create_product(
    product_data: ProductCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new product.
    """
    try:
        product_service = ProductService(db)
        product = await product_service.create_product(product_data)
        return product
    except ProductCreationError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{product_id}", response_model=ProductRead)
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Get a product by ID.
    """
    try:
        product_service = ProductService(db)
        product = await product_service.get_product(product_id)
        return product
    except ProductNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/", response_model=dict)
async def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    search: Optional[str] = None,
    category: Optional[str] = None,
    brand: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    List products with filtering and pagination.
    """
    product_service = ProductService(db)
    result = await product_service.list_products(
        page=page,
        page_size=page_size,
        search=search,
        category=category,
        brand=brand
    )
    return result

@router.patch("/{product_id}", response_model=ProductRead)
async def update_product(
    product_id: int,
    product_data: ProductUpdate,
    db: AsyncSession = Depends(get_db)
):
    """
    Update a product.
    """
    try:
        product_service = ProductService(db)
        product = await product_service.update_product(product_id, product_data)
        return product
    except ProductNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.delete("/{product_id}", response_model=bool)
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a product.
    """
    try:
        product_service = ProductService(db)
        result = await product_service.delete_product(product_id)
        return result
    except ProductNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))