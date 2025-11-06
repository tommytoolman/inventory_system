"""
Purpose: The central service for managing the core Product entity.

Role: Foundational service managing the core data object that other platform services relate to.

This is a class which provides standard CRUD operations :
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

plus status updates (update_product_status) and SKU existence checks. It uses helper functions from app.core.utils (like model_to_schema, paginate_query). 
It returns data using Pydantic schemas (ProductRead). Defines relevant custom exceptions. 
Note: It contains commented-out code (_create_ebay_listing) suggesting a previous design where creating a product might have directly 
reated platform listings; this logic seems to have moved (likely correctly) to more specific services like EbayService.

"""

from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, exists, or_, and_
from datetime import datetime, timezone

from app.core.enums import ProductStatus, ListingStatus, SyncStatus, EbayListingStatus
from app.core.exceptions import ProductCreationError, ProductNotFoundError
from app.core.utils import model_to_schema, models_to_schemas, paginate_query
from app.models.product import Product
from app.models.platform_common import PlatformCommon
from app.schemas.product import ProductCreate, ProductRead, ProductUpdate
from app.schemas.platform.ebay import EbayListingCreate


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
    ) -> ProductRead:
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
            # Check if SKU exists as a draft
            existing_query = await self.db.execute(
                select(Product)
                .where(Product.sku == product_data.sku)
                .order_by(Product.id.desc())
            )
            existing_product = existing_query.scalars().first()

            if existing_product:
                if existing_product.status == ProductStatus.DRAFT:
                    # Update the existing draft product
                    for key, value in product_data.model_dump(exclude_unset=True).items():
                        setattr(existing_product, key, value)
                    product = existing_product
                    await self.db.flush()
                else:
                    raise ProductCreationError(f"SKU '{product_data.sku}' already exists")
            else:
                # Create new product
                product = Product(**product_data.model_dump(exclude_unset=True))
                self.db.add(product)
                await self.db.flush()  # Get product ID without committing

            # If eBay data provided, create platform listing
            if ebay_data:
                await self._create_ebay_listing(product.id, ebay_data)

            await self.db.commit()

            # Refresh the product to ensure all fields are loaded
            await self.db.refresh(product)

            # Return the created product as a schema (convert from model to schema)
            return await model_to_schema(product, ProductRead)

        except Exception as e:
            await self.db.rollback()
            raise ProductCreationError(f"Failed to create product: {str(e)}")

    async def get_product(self, product_id: int) -> Optional[ProductRead]:
        """
        Retrieves a product by ID.
        
        Args:
            product_id: Product ID
            
        Returns:
            Product data or None if not found
            
        Raises:
            ProductNotFoundError: If product not found
        """
        query = select(Product).where(Product.id == product_id)
        result = await self.db.execute(query)
        product = await result.scalar_one_or_none()
        
        if not product:
            raise ProductNotFoundError(f"Product with ID {product_id} not found")
            
        return await model_to_schema(product, ProductRead)

    async def get_product_model_instance(self, product_id: int) -> Optional[Product]: # Returns the DB Model
        """
        Retrieves a product SQLAlchemy model instance by ID.
        This method should also handle eager loading of necessary relationships if not already handled.
        """
        # The query needs to ensure related data (images, category object if relational, etc.) is loaded
        # For example, if product.category is a relationship:
        # query = select(Product).options(selectinload(Product.category), selectinload(Product.images_relation_if_any)).where(Product.id == product_id)
        query = select(Product).where(Product.id == product_id) # Basic query

        # If you have specific relationships that _prepare_vr_payload_from_product_object needs,
        # and they are not loaded by default or by accessing them (due to lazy loading settings),
        # you'd add .options(selectinload(Product.your_relationship)) to the query above.
        # For fields like product.images (JSONB), product.image_urls (ARRAY), product.category (String),
        # no special selectinload is needed as they are direct columns.

        result = await self.db.execute(query)
        product_model = result.scalar_one_or_none() # Returns the Product SQLAlchemy model instance

        if not product_model:
            # You might still raise ProductNotFoundError or let the route handle None
            # raise ProductNotFoundError(f"Product model with ID {product_id} not found")
            return None

        return product_model

    async def list_products(
        self,
        page: int = 1,
        page_size: int = 10,
        search: Optional[str] = None,
        category: Optional[str] = None,
        brand: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        List products with filtering and pagination.
        
        Args:
            page: Page number
            page_size: Items per page
            search: Search query
            category: Filter by category
            brand: Filter by brand
            
        Returns:
            Dictionary with paginated products and pagination info
        """
        query = select(Product)
        
        # Apply filters
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                or_(
                    Product.brand.ilike(search_term),
                    Product.model.ilike(search_term),
                    Product.sku.ilike(search_term),
                    Product.description.ilike(search_term)
                )
            )
        
        if category:
            query = query.filter(Product.category == category)
        
        if brand:
            query = query.filter(Product.brand == brand)
        
        # Apply pagination and get results
        pagination_result = await paginate_query(
            query, 
            self.db, 
            page=page, 
            page_size=page_size
        )
        
        # Convert models to schemas
        items = pagination_result.pop('items')
        product_schemas = await models_to_schemas(items, ProductRead)
        
        # Return paginated result
        return {
            **pagination_result,
            "items": product_schemas
        }

    async def update_product(
        self,
        product_id: int,
        product_data: ProductUpdate
    ) -> ProductRead:
        """
        Update a product.
        
        Args:
            product_id: Product ID
            product_data: Product data to update
            
        Returns:
            Updated product data
            
        Raises:
            ProductNotFoundError: If product not found
        """
        # Get the product
        query = select(Product).where(Product.id == product_id)
        result = await self.db.execute(query)
        product = await result.scalar_one_or_none()
        
        if not product:
            raise ProductNotFoundError(f"Product with ID {product_id} not found")
        
        # Update the product with non-None values from the update schema
        update_data = product_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if value is not None and hasattr(product, key):
                setattr(product, key, value)
        
        # Update timestamp
        product.updated_at = datetime.now(timezone.utc)()
        
        # Commit changes
        await self.db.commit()
        
        # Return updated product
        return await model_to_schema(product, ProductRead)

    async def delete_product(self, product_id: int) -> bool:
        """
        Delete a product.
        
        Args:
            product_id: Product ID
            
        Returns:
            True if deleted, False otherwise
            
        Raises:
            ProductNotFoundError: If product not found
        """
        query = select(Product).where(Product.id == product_id)
        result = await self.db.execute(query)
        product = await result.scalar_one_or_none()
        
        if not product:
            raise ProductNotFoundError(f"Product with ID {product_id} not found")
        
        await self.db.delete(product)
        await self.db.commit()
        
        return True

    async def update_product_status(
        self,
        product_id: int,
        status: ProductStatus
    ) -> Optional[Product]:
        """Updates product status."""
        product = await self.get_product(product_id)
        if product:
            product.status = status
            product.updated_at = datetime.now(timezone.utc)()
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
