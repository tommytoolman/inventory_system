"""
This is a class which will:
- Create the product
- Create the platform_common entry
- Create the eBay listing in draft mode
- Handle validation and rollbacks

Key features of this service:
- Handles both product creation and optional eBay listing creation in a single transaction
- Uses proper error handling and rollbacks
- Keeps eBay listings in draft status
- Maintains sync status for platform integrations
- Provides basic product status management

"""

from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, exists
from datetime import datetime

from app.models.product import Product, ProductStatus
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.models.ebay import EbayListing, EbayListingStatus
from app.schemas.product import ProductCreate
from app.schemas.platform.ebay import EbayListingCreate
from app.core.exceptions import ProductCreationError

class ProductService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def sku_exists(self, sku: str) -> bool:
        """Check if a SKU already exists."""
        query = select(exists().where(Product.sku == sku))
        result = await self.db.scalar(query)
        return result


    async def create_product(
        self,
        product_data: ProductCreate,
        ebay_data: Optional[Dict[str, Any]] = None
    ) -> Product:
        """
        Creates a product and optionally initializes eBay listing.

        Args:
            product_data: Validated product data
            ebay_data: Optional eBay-specific listing data

        Returns:
            Created product instance

        Raises:
            ProductCreationError: If product creation fails
        """
        try:
            # Check if SKU exists
            if await self.sku_exists(product_data.sku):
                raise ProductCreationError(f"SKU '{product_data.sku}' already exists")
            
            # Create product
            product = Product(**product_data.model_dump(exclude_unset=True))
            self.db.add(product)
            await self.db.flush()  # Get product ID without committing

            # If eBay data provided, create platform listing
            if ebay_data:
                await self._create_ebay_listing(product.id, ebay_data)

            await self.db.commit()
            # return product
            # Previously we returned product but ... we hit a lazy loading problem. Here we switch to eager loading.

            from sqlalchemy.orm import selectinload
            query = select(Product).options(selectinload(Product.platform_listings)).where(Product.id == product.id)
            result = await self.db.execute(query)
            return result.scalar_one()

        except Exception as e:
            await self.db.rollback()
            raise ProductCreationError(f"Failed to create product: {str(e)}")

    async def _create_ebay_listing(
        self,
        product_id: int,
        ebay_data: Dict[str, Any]
    ) -> None:
        """
        Creates platform_common entry and eBay listing in draft status.
        """
        # Create platform_common entry
        platform_common = PlatformCommon(
            product_id=product_id,
            platform_name="ebay",
            status=ListingStatus.DRAFT.value,  # Use .value here
            sync_status=SyncStatus.PENDING.value,  # Use .value here
            platform_specific_data=ebay_data.get("item_specifics", {})
        )
        self.db.add(platform_common)
        await self.db.flush()

        # Create eBay listing
        ebay_listing = EbayListing(
            platform_id=platform_common.id,
            ebay_category_id=ebay_data.get("category_id"),
            ebay_condition_id=ebay_data.get("condition_id"),
            price=ebay_data.get("price", 0),
            listing_duration=ebay_data.get("duration", "GTC"),
            item_specifics=ebay_data.get("item_specifics", {}),
            listing_status=EbayListingStatus.DRAFT.value  # Use .value here
        )
        self.db.add(ebay_listing)

    async def get_product(self, product_id: int) -> Optional[Product]:
        """Retrieves a product by ID with its platform listings."""
        query = select(Product).where(Product.id == product_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def update_product_status(
        self,
        product_id: int,
        status: ProductStatus
    ) -> Optional[Product]:
        """Updates product status."""
        product = await self.get_product(product_id)
        if product:
            product.status = status
            product.updated_at = datetime.utcnow()
            await self.db.commit()
        return product

class ProductServiceError(Exception):
    """Base exception for product service errors."""
    pass

class ProductCreationError(ProductServiceError):
    """Raised when product creation fails."""
    pass

class ProductNotFoundError(ProductServiceError):
    """Raised when product is not found."""
    pass

class EbayListingError(ProductServiceError):
    """Raised when eBay listing creation fails."""
    pass