
"""
Note - may not be used as going to shopify so this is an outline in case we need in future of if Shopify uses webhooks.

Purpose: Contains logic to process incoming webhook events, specifically shown here is process_website_sale for handling sales from the website.

Functionality: Parses the webhook payload, creates a Sale record in the database, updates the local Product quantity 
(Note: It directly updates product.quantity -= 1. Ensure your Product model actually has a quantity field, as inventory might be tracked differently, 
e.g., purely via platform listings). It then attempts to trigger cross-platform sync via sync_stock_to_platforms.

Role & Issues: Demonstrates handling of incoming events. However, the sync_stock_to_platforms function has issues:
It instantiates StockManager directly, which is problematic. The StockManager instance created by app/integrations/setup.py should be used (likely accessed via dependency injection in a real FastAPI route handler calling this processor). Instantiating it here creates a new, empty manager that doesn't know about the registered platforms.
It calls stock_manager.sync_product(product), but StockManager doesn't have a sync_product method. It should likely create a StockUpdateEvent and put it on the manager's update_queue. This needs correction.
Contains an unused MockWebhookProcessor class.

"""
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.sale import Sale
from app.models.product import Product
from datetime import datetime, timezone

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