import asyncio
from datetime import datetime

from app.database import async_session
from app.services.product_service import ProductService
from app.schemas.product import ProductCreate

async def test_create_product():
    async with async_session() as session:
        product_service = ProductService(session)
        
        # Create test product data
        product_data = ProductCreate(
            sku="TEST-001",
            brand="Fender",
            model="Stratocaster",
            year=1954,
            category="Electric Guitar",
            condition="EXCELLENT",
            description="Test product",
            base_price=1499.99,
        )
        
        try:
            # Create product
            product = await product_service.create_product(product_data)
            print(f"Created product with ID: {product.id}")
            
            # Verify product was created
            retrieved_product = await product_service.get_product(product.id)
            print(f"Retrieved product: {retrieved_product.brand} {retrieved_product.model}")
            print(f"Status: {retrieved_product.status}")
            print(f"Created at: {retrieved_product.created_at}")
            
        except Exception as e:
            print(f"Error creating product: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_create_product())