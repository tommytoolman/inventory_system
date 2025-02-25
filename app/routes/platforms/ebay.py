# Example route showing service integration
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.product import ProductCreate
from app.schemas.platform.ebay import EbayListingCreate
from app.services.product_service import ProductService
from app.services.ebay_service import EbayService
from app.dependencies import get_db

router = APIRouter()

@router.post("/products/with-ebay")
async def create_product_with_ebay(
    product_data: ProductCreate,
    ebay_data: EbayListingCreate,
    db: AsyncSession = Depends(get_db)
):
    # Initialize services
    product_service = ProductService(db)
    ebay_service = EbayService(db)

    # Create product and get platform_common ID
    product = await product_service.create_product(product_data)
    
    # Create eBay listing
    ebay_listing = await ebay_service.create_draft_listing(
        product.platform_listings[0].id,  # First platform listing is eBay
        ebay_data
    )

    return {
        "product": product,
        "ebay_listing": ebay_listing
    }   