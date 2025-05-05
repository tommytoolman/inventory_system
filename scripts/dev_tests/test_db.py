# tests/test_db.py
import asyncio
from datetime import datetime, timezone
from sqlalchemy import select, delete

from app.core.enums import ProductStatus
from app.database import get_session
from app.models.product import Product
from app.models.platform_common import PlatformListing
from app.models.ebay import EbayListing
from app.models.reverb import ReverbListing
from app.models.vr import VRListing
from app.models.website import WebsiteListing


async def cleanup_test_data():
    """Remove any existing test data in the correct order"""
    async with get_session() as session:
        try:
            # First get all test products
            result = await session.execute(
                select(Product).where(Product.sku.like('TEST-%'))
            )
            test_products = result.scalars().all()
            
            for product in test_products:
                # Get platform listings for this product
                platform_result = await session.execute(
                    select(PlatformListing).where(PlatformListing.product_id == product.id)
                )
                platform_listings = platform_result.scalars().all()
                
                for platform_listing in platform_listings:
                    # Delete platform-specific listings first
                    await session.execute(
                        delete(EbayListing).where(EbayListing.platform_id == platform_listing.id)
                    )
                    await session.execute(
                        delete(ReverbListing).where(ReverbListing.platform_id == platform_listing.id)
                    )
                    await session.execute(
                        delete(VRListing).where(VRListing.platform_id == platform_listing.id)
                    )
                    await session.execute(
                        delete(WebsiteListing).where(WebsiteListing.platform_id == platform_listing.id)
                    )
                    
                    # Then delete the platform listing
                    await session.delete(platform_listing)
                
                # Finally delete the product
                await session.delete(product)
            
            await session.commit()
            print("Cleaned up previous test data")
            
        except Exception as e:
            print(f"Cleanup error: {e}")
            await session.rollback()

async def test_create_product():
    # Generate unique SKU using timestamp
    unique_sku = f"TEST-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    async with get_session() as session:
        try:
            # Create a product
            product = Product(
                sku=unique_sku,
                brand="Fender",
                model="Stratocaster",
                year=1965,
                category="Electric Guitars",
                condition="Excellent",
                description="Test product",
                base_price=10000.00,
                cost_price=8000.00,
                status=ProductStatus.ACTIVE
            )
            session.add(product)
            await session.commit()
            print(f"Created product: {product.sku} - {product.brand} {product.model}")

            # Create platform listings
            platform_common = PlatformListing(
                product_id=product.id,
                platform_name="ebay",
                external_id=f"EBAY-{unique_sku}",
                status="active"
            )
            session.add(platform_common)
            await session.commit()
            print(f"Created platform listing: {platform_common.platform_name}")

            ebay_listing = EbayListing(
                platform_id=platform_common.id,
                ebay_category_id="33034",
                ebay_condition_id="3000",
                item_specifics={"Brand": "Fender", "Model": "Stratocaster"}
            )
            session.add(ebay_listing)
            await session.commit()
            print("Created eBay listing")

            # Query and verify
            result = await session.execute(
                select(Product).where(Product.sku == unique_sku)
            )
            test_product = result.scalar_one()
            print(f"\nVerification:")
            print(f"Retrieved product: {test_product.sku} - {test_product.brand} {test_product.model}")
            
            # Get associated listings
            result = await session.execute(
                select(PlatformListing).where(PlatformListing.product_id == test_product.id)
            )
            listings = result.scalars().all()
            for listing in listings:
                print(f"Retrieved platform listing: {listing.platform_name} - {listing.external_id}")

        except Exception as e:
            print(f"Error: {e}")
            await session.rollback()
            raise

async def run_tests():
    await cleanup_test_data()
    await test_create_product()

if __name__ == "__main__":
    asyncio.run(run_tests())