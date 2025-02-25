
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.sale import Sale
from app.models.product import Product
from datetime import datetime

class MockWebhookProcessor:
    pass

async def process_website_sale(payload: dict, db: AsyncSession):
    """Process a sale webhook from the website"""
    # Extract sale information from the payload
    sale_data = {
        "platform": "website",
        "platform_order_id": payload["order_id"],
        "product_id": payload["product_id"],
        "sale_price": payload["price"],
        "sale_date": datetime.fromisoformat(payload["sale_date"]),
        "buyer_info": {
            "name": payload["buyer"]["name"],
            "email": payload["buyer"]["email"],
            "shipping_address": payload["shipping_address"]
        }
    }
    
    
    # Create sale record
    sale = Sale(**sale_data)
    db.add(sale)
    
    # Update product inventory
    product = await db.get(Product, payload["product_id"])
    if product:
        product.quantity -= 1
        if product.quantity <= 0:
            # Trigger inventory sync to other platforms
            await sync_stock_to_platforms(product)
    
    await db.commit()

async def sync_stock_to_platforms(product):
    """Synchronize product stock levels across all platforms"""
    from app.integrations.stock_manager import StockManager  # Import here to avoid circular imports

    stock_manager = StockManager()
    await stock_manager.sync_product(product)