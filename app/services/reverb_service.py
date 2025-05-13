# app.services.reverb_service.py
import json
import logging

from datetime import datetime, timezone    
from fastapi import HTTPException
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, text

from app.models.product import Product, ProductStatus, ProductCondition
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.models.product import Product
from app.models.reverb import ReverbListing
from app.services.reverb.client import ReverbClient
from app.core.config import Settings
from app.core.exceptions import ListingNotFoundError, ReverbAPIError


logger = logging.getLogger(__name__)

class ReverbService:
    """
    Service for interacting with Reverb marketplace.
    
    This class manages the integration between our inventory system and
    the Reverb platform, handling data transformation, error handling,
    and synchronization.
    """
    
    def __init__(self, db: AsyncSession, settings: Settings):
        """
        Initialize the Reverb service with database session and settings.
        
        Args:
            db: Database session for data access
            settings: Application settings including API credentials
        """
        self.db = db
        self.settings = settings
        
        # Use sandbox API for testing if enabled in settings
        use_sandbox = self.settings.REVERB_USE_SANDBOX
        api_key = self.settings.REVERB_SANDBOX_API_KEY if use_sandbox else self.settings.REVERB_API_KEY
        
        self.client = ReverbClient(api_key=api_key, use_sandbox=use_sandbox)
    
    async def get_categories(self) -> Dict:
        """
        Get all categories from Reverb.
        
        Returns:
            Dict: Categories data
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        try:
            return await self.client.get_categories()
        except Exception as e:
            logger.error(f"Error fetching categories: {str(e)}")
            if isinstance(e, ReverbAPIError):
                raise
            raise ReverbAPIError(f"Failed to fetch categories: {str(e)}")
    
    async def get_category(self, uuid: str) -> Dict:
        """
        Get a specific category by UUID.
        
        Args:
            uuid: Category UUID
            
        Returns:
            Dict: Category data
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        try:
            return await self.client.get_category(uuid)
        except Exception as e:
            logger.error(f"Error fetching category {uuid}: {str(e)}")
            if isinstance(e, ReverbAPIError):
                raise
            raise ReverbAPIError(f"Failed to fetch category {uuid}: {str(e)}")
    
    async def get_conditions(self) -> Dict:
        """
        Get all listing conditions from Reverb.
        
        Returns:
            Dict: Listing conditions data
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        try:
            return await self.client.get_listing_conditions()
        except Exception as e:
            logger.error(f"Error fetching conditions: {str(e)}")
            if isinstance(e, ReverbAPIError):
                raise
            raise ReverbAPIError(f"Failed to fetch conditions: {str(e)}")
            
    async def fetch_and_store_condition_mapping(self) -> Dict[str, str]:
        """
        Fetch conditions from Reverb and store for future use
        
        Returns:
            Dict[str, str]: Mapping of condition display names to UUIDs
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        try:
            response = await self.client.get_listing_conditions()
            
            # Extract conditions and create a mapping of display names to UUIDs
            condition_mapping = {}
            
            if 'conditions' in response:
                for condition in response['conditions']:
                    if 'display_name' in condition and 'uuid' in condition:
                        condition_mapping[condition['display_name']] = condition['uuid']
            
            return condition_mapping
        except Exception as e:
            logger.error(f"Error fetching conditions: {str(e)}")
            if isinstance(e, ReverbAPIError):
                raise
            raise ReverbAPIError(f"Failed to fetch conditions: {str(e)}")
    
    async def create_draft_listing(self, reverb_listing_id: int, listing_data: Dict[str, Any] = None) -> ReverbListing:
        """
        Create a draft listing on Reverb based on product data.
        
        Args:
            reverb_listing_id: Database ID of the ReverbListing
            listing_data: Optional custom listing data overrides
            
        Returns:
            ReverbListing: Updated database record with Reverb listing ID
            
        Raises:
            ListingNotFoundError: If listing not found
            ReverbAPIError: If the API request fails
        """
        try:
            # Get the ReverbListing and associated PlatformCommon and Product
            listing = await self._get_reverb_listing(reverb_listing_id)
            if not listing:
                raise ListingNotFoundError(f"ReverbListing {reverb_listing_id} not found")
            
            platform_common = await self._get_platform_common(listing.platform_id)
            if not platform_common or not platform_common.product_id:
                raise ListingNotFoundError(f"PlatformCommon {listing.platform_id} or related Product not found")
            
            product = await self._get_product(platform_common.product_id)
            if not product:
                raise ListingNotFoundError(f"Product {platform_common.product_id} not found")
            
            # Prepare the listing data for Reverb API
            api_listing_data = listing_data or self._prepare_listing_data(listing, product)
            
            # Create the listing on Reverb
            response = await self.client.create_listing(api_listing_data)
            
            # Update database with the new Reverb listing ID
            if 'listing' in response and 'id' in response['listing']:
                reverb_id = str(response['listing']['id'])
                
                # Update the ReverbListing record
                listing.reverb_listing_id = reverb_id
                
                # Update platform_common sync status
                platform_common.sync_status = SyncStatus.SYNCED.value
                
                # Save changes to database
                self.db.add(listing)
                self.db.add(platform_common)
                await self.db.flush()
                
                logger.info(f"Created draft listing on Reverb with ID {reverb_id}")
                return listing
            else:
                logger.error(f"Failed to create listing: No listing ID in response: {response}")
                raise ReverbAPIError("Failed to create listing: No listing ID in response")
                
        except Exception as e:
            logger.error(f"Error creating draft listing: {str(e)}")
            if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
                raise
            raise ReverbAPIError(f"Failed to create draft listing: {str(e)}")
    
    async def get_listing_details(self, reverb_listing_id: int) -> Dict:
        """
        Get detailed information about a listing from Reverb API
        
        Args:
            reverb_listing_id: Database ID of the ReverbListing
            
        Returns:
            Dict: Listing details from Reverb API
            
        Raises:
            ListingNotFoundError: If listing not found
            ReverbAPIError: If the API request fails
        """
        try:
            # Get the ReverbListing record
            listing = await self._get_reverb_listing(reverb_listing_id)
            if not listing or not listing.reverb_listing_id:
                raise ListingNotFoundError(f"ReverbListing {reverb_listing_id} not found or has no Reverb ID")
            
            # Fetch the listing details from Reverb API
            return await self.client.get_listing(listing.reverb_listing_id)
        
        except Exception as e:
            logger.error(f"Error getting listing details: {str(e)}")
            if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
                raise
            raise ReverbAPIError(f"Failed to get listing details: {str(e)}")
    
    async def update_inventory(self, reverb_listing_id: int, quantity: int) -> bool:
        """
        Update the inventory quantity of a listing on Reverb
        
        Args:
            reverb_listing_id: Database ID of the ReverbListing
            quantity: New inventory quantity
            
        Returns:
            bool: Success status
            
        Raises:
            ListingNotFoundError: If listing not found
            ReverbAPIError: If the API request fails
        """
        try:
            # Get the ReverbListing record
            listing = await self._get_reverb_listing(reverb_listing_id)
            if not listing or not listing.reverb_listing_id:
                raise ListingNotFoundError(f"ReverbListing {reverb_listing_id} not found or has no Reverb ID")
            
            # Prepare inventory update data
            inventory_data = {
                "inventory": quantity,
                "has_inventory": quantity > 0
            }
            
            # Update the listing on Reverb
            await self.client.update_listing(listing.reverb_listing_id, inventory_data)
            
            # Update local database record
            listing.inventory_quantity = quantity
            listing.has_inventory = quantity > 0
            self.db.add(listing)
            await self.db.flush()
            
            logger.info(f"Updated inventory for listing {listing.reverb_listing_id} to {quantity}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating inventory: {str(e)}")
            if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
                raise
            raise ReverbAPIError(f"Failed to update inventory: {str(e)}")
    
    async def publish_listing(self, reverb_listing_id: int) -> bool:
        """
        Publish a draft listing on Reverb
        
        Args:
            reverb_listing_id: Database ID of the ReverbListing
            
        Returns:
            bool: Success status
            
        Raises:
            ListingNotFoundError: If listing not found
            ReverbAPIError: If the API request fails
        """
        try:
            # Get the ReverbListing and PlatformCommon records
            listing = await self._get_reverb_listing(reverb_listing_id)
            if not listing or not listing.reverb_listing_id:
                raise ListingNotFoundError(f"ReverbListing {reverb_listing_id} not found or has no Reverb ID")
            
            platform_common = await self._get_platform_common(listing.platform_id)
            if not platform_common:
                raise ListingNotFoundError(f"PlatformCommon {listing.platform_id} not found")
            
            # Publish the listing on Reverb
            publish_data = {"publish": True}
            await self.client.update_listing(listing.reverb_listing_id, publish_data)
            
            # Update local database records
            platform_common.status = ListingStatus.ACTIVE.value
            listing.reverb_state = "published"
            
            self.db.add(platform_common)
            self.db.add(listing)
            await self.db.flush()
            
            logger.info(f"Published listing {listing.reverb_listing_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error publishing listing: {str(e)}")
            if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
                raise
            raise ReverbAPIError(f"Failed to publish listing: {str(e)}")
    
    async def end_listing(self, reverb_listing_id: int, reason: str = "not_for_sale") -> bool:
        """
        End a listing on Reverb
        
        Args:
            reverb_listing_id: Database ID of the ReverbListing
            reason: Reason for ending the listing
            
        Returns:
            bool: Success status
            
        Raises:
            ListingNotFoundError: If listing not found
            ReverbAPIError: If the API request fails
        """
        try:
            # Get the ReverbListing and PlatformCommon records
            listing = await self._get_reverb_listing(reverb_listing_id)
            if not listing or not listing.reverb_listing_id:
                raise ListingNotFoundError(f"ReverbListing {reverb_listing_id} not found or has no Reverb ID")
            
            platform_common = await self._get_platform_common(listing.platform_id)
            if not platform_common:
                raise ListingNotFoundError(f"PlatformCommon {listing.platform_id} not found")
            
            # End the listing on Reverb
            end_data = {"state": "ended"}
            await self.client.update_listing(listing.reverb_listing_id, end_data)
            
            # Update local database records
            platform_common.status = ListingStatus.ENDED.value
            listing.reverb_state = "ended"
            
            self.db.add(platform_common)
            self.db.add(listing)
            await self.db.flush()
            
            logger.info(f"Ended listing {listing.reverb_listing_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error ending listing: {str(e)}")
            if isinstance(e, (ListingNotFoundError, ReverbAPIError)):
                raise
            raise ReverbAPIError(f"Failed to end listing: {str(e)}")

    async def run_import_process(self, api_key: str, save_only=False):
        """Run the Reverb inventory import process."""
        try:
            print("Starting Reverb.run_import_process")
            print(f"API key provided: {'Yes' if api_key else 'No'}")
            
            # Initialize client
            client = ReverbClient(api_key)  # Reverb uses API key, not username/password
            
            # Get all listings from Reverb
            print("Downloading listings from Reverb API...")
            listings = await client.get_all_listings()  # This method exists in your ReverbClient
            
            if not listings:
                print("Reverb listings download failed - received None or empty")
                return {"status": "error", "message": "No Reverb listings data received"}
            
            print(f"Successfully downloaded inventory with {len(listings)} items")
            print(f"Sample data: {listings[0] if listings else 'None'}")
            
            if save_only:
                # Save to file for testing
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                json_path = Path(f"data/reverb_{timestamp}.json")
                json_path.parent.mkdir(parents=True, exist_ok=True)
                
                with open(json_path, 'w') as f:
                    json.dump(listings, f, indent=2)
                
                print(f"Saved Reverb data to: {json_path}")
                return {
                    "status": "success", 
                    "message": f"Reverb inventory saved with {len(listings)} records",
                    "count": len(listings),
                    "saved_to": str(json_path)
                }
            
            # Process inventory updates
            print("Processing inventory updates...")
            # Fix: Call the correct Reverb methods
            removed_stats = await self._mark_removed_reverb_products(listings)
            update_stats = await self._process_reverb_listings(listings)

            # Combine results
            result = {
                **update_stats,
                **removed_stats,
                "import_type": "UPDATE-BASED (No deletions)",
                "total_processed": len(listings)
            }
            
            print(f"Inventory update processing complete: {result}")
            return {
                "status": "success",
                "message": f"Reverb inventory processed successfully",
                "processed": len(listings),
                "created": result.get("created", 0),
                "updated": result.get("updated", 0),
                "errors": result.get("errors", 0),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        
        except Exception as e:
            import traceback
            error_traceback = traceback.format_exc()
            print(f"Exception in ReverbService.run_import_process: {str(e)}")
            print(f"Traceback: {error_traceback}")
            return {"status": "error", "message": str(e)}


    # Private helper methods
    
    async def _get_platform_common(self, platform_id: int) -> Optional[PlatformCommon]:
        """Get platform_common record by ID with associated product"""
        query = select(PlatformCommon).where(PlatformCommon.id == platform_id)
        result = await self.db.execute(query)
        return result.scalars().first()
    
    async def _get_product(self, product_id: int) -> Optional[Product]:
        """Get product record by ID"""
        query = select(Product).where(Product.id == product_id)
        result = await self.db.execute(query)
        return result.scalars().first()
    
    async def _get_reverb_listing(self, listing_id: int) -> Optional[ReverbListing]:
        """Get reverb_listing record by ID"""
        query = select(ReverbListing).where(ReverbListing.id == listing_id)
        result = await self.db.execute(query)
        return result.scalars().first()
    
    def _prepare_listing_data(self, listing: ReverbListing, product: Product) -> Dict[str, Any]:
        """
        Prepare listing data for Reverb API
        
        Args:
            listing: ReverbListing record
            product: Associated Product record
            
        Returns:
            Dict: Listing data formatted for Reverb API
        """
        data = {
            "title": product.title or f"{product.brand} {product.model}",
            "description": product.description or "",
            "make": product.brand,
            "model": product.model,
            # Format condition as object with UUID
            "condition": {
                "uuid": self._get_condition_uuid(product.condition)
            },
            # Format price as object with amount and currency
            "price": {
                "amount": str(product.base_price),  # Must be a string
                "currency": "USD" if self.client.use_sandbox else "GBP"  # USD for sandbox, GBP for production
            },
            "shipping": {
                "local": True,
                "us": True,
                "us_rate": "25.00"  # Default shipping rate
            },
            "categories": [
                {"uuid": listing.reverb_category_uuid or "dfd39027-d134-4353-b9e4-57dc6be791b9"}  # Default to Electric Guitars
            ],
            "has_inventory": listing.has_inventory,
            "inventory": listing.inventory_quantity or 1,
            "offers_enabled": listing.offers_enabled
        }
        
        # Add photos if available
        if listing.photos:
            data["photos"] = listing.photos.split(",")
            
        # Add year if available
        if product.year:
            data["year"] = str(product.year)
            
        # Add finish if available
        if product.finish:
            data["finish"] = product.finish
            
        return data

    def _get_condition_uuid(self, condition_name: str) -> str:
        """Map condition name to UUID"""
        condition_map = {
            "Mint": "ec942c5e-fd9d-4a70-af95-ce686ed439e5",
            "Excellent": "df268ad1-c462-4ba6-b6db-e007e23922ea",
            "Very Good": "ae4d9114-1bd7-4ec5-a4ba-6653af5ac84d", 
            "Good": "ddadff2a-188c-42e0-be90-ebed197400a3",
            "Fair": "a2356006-97f9-487c-bd68-6c148a8ffe93",
            "Poor": "41b843b5-af33-4f37-9e9e-eec54aac6ce4",
            "Non Functioning": "196adee9-5415-4b5d-910f-39f2eb72e92f"
        }
        # Default to "Excellent" condition if not found
        return condition_map.get(condition_name, "df268ad1-c462-4ba6-b6db-e007e23922ea")
    
    async def _process_reverb_listings(self, listings: List[Dict]) -> Dict[str, int]:
        """Process Reverb listings (update existing, create new)"""
        stats = {"total": len(listings), "created": 0, "updated": 0, "errors": 0}
        
        try:
            for listing in listings:
                try:
                    # Extract Reverb listing ID
                    reverb_id = str(listing.get('id'))
                    sku = f"REV-{reverb_id}"
                    
                    # Check if product exists
                    stmt = text("SELECT id FROM products WHERE sku = :sku")
                    result = await self.db.execute(stmt, {"sku": sku})
                    existing_product_id = result.scalar_one_or_none()
                    
                    if existing_product_id:
                        # Update existing product
                        await self._update_existing_product(existing_product_id, listing)
                        stats["updated"] += 1
                    else:
                        # Create new product
                        await self._create_new_product(listing, sku)
                        stats["created"] += 1
                        
                except Exception as e:
                    logger.error(f"Error processing listing {listing.get('id')}: {e}")
                    stats["errors"] += 1
            
            await self.db.commit()
            return stats
            
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error in _process_reverb_listings: {e}")
            raise

    async def _mark_removed_reverb_products(self, listings: List[Dict]) -> Dict[str, int]:
        """Mark products that are no longer on Reverb as removed"""
        stats = {"marked_removed": 0}
        
        # Get Reverb listing IDs from current data
        current_ids = {f"REV-{listing.get('id')}" for listing in listings if listing.get('id')}
        
        # Find products in DB but not in current listings
        stmt = text("SELECT sku, id FROM products WHERE sku LIKE 'REV-%' AND sku != ALL(:current_skus)")
        result = await self.db.execute(stmt, {"current_skus": tuple(current_ids)})
        removed_products = result.fetchall()
        
        # Mark as removed
        for sku, product_id in removed_products:
            platform_update = text("""
                UPDATE platform_common 
                SET status = 'REMOVED', 
                    sync_status = 'SYNCED',
                    last_sync = timezone('utc', now()),
                    updated_at = timezone('utc', now())
                WHERE product_id = :product_id AND platform_name = 'reverb'
            """)
            await self.db.execute(platform_update, {"product_id": product_id})
            stats["marked_removed"] += 1
        
        logger.info(f"Marked {stats['marked_removed']} Reverb products as removed")
        return stats

    async def _update_existing_product(self, product_id: int, listing: Dict):
        """Update an existing product with new Reverb data"""
        # Extract data from listing
        is_sold = listing.get('state', {}).get('slug') == 'sold'
        new_status = ProductStatus.SOLD if is_sold else ProductStatus.ACTIVE
        
        # Update product
        update_stmt = text("""
            UPDATE products 
            SET base_price = :price,
                description = :description,
                status = :status,
                updated_at = timezone('utc', now())
            WHERE id = :product_id
        """)
        
        await self.db.execute(update_stmt, {
            "product_id": product_id,
            "price": float(listing.get('price', {}).get('amount', 0)) if listing.get('price') else 0,
            "description": listing.get('description', ''),
            "status": new_status.value
        })
        
        # Update platform_common
        platform_update = text("""
            UPDATE platform_common 
            SET status = :status,
                sync_status = 'SYNCED',
                last_sync = timezone('utc', now()),
                updated_at = timezone('utc', now())
            WHERE product_id = :product_id AND platform_name = 'reverb'
        """)
        
        platform_status = ListingStatus.SOLD if is_sold else ListingStatus.ACTIVE
        await self.db.execute(platform_update, {
            "product_id": product_id,
            "status": platform_status.value
        })

    async def _create_new_product(self, listing: Dict, sku: str):
        """Create a new product from Reverb listing data"""
        # Extract data from listing
        brand = listing.get('make', 'Unknown')
        model = listing.get('model', 'Unknown')
        
        # Get price
        price = 0.0
        if listing.get('price') and listing.get('price', {}).get('amount'):
            price = float(listing.get('price', {}).get('amount', 0))
        
        # Get year
        year = None
        if listing.get('year'):
            try:
                year = int(listing.get('year'))
            except:
                pass
        
        # Determine condition
        condition = ProductCondition.GOOD  # Default
        if listing.get('condition', {}).get('display_name'):
            condition_name = listing.get('condition', {}).get('display_name', '').lower()
            condition_map = {
                'mint': ProductCondition.EXCELLENT,
                'excellent': ProductCondition.EXCELLENT,
                'very good': ProductCondition.VERYGOOD,
                'good': ProductCondition.GOOD,
                'fair': ProductCondition.FAIR,
                'poor': ProductCondition.POOR
            }
            condition = condition_map.get(condition_name, ProductCondition.GOOD)
        
        # Check if sold
        is_sold = listing.get('state', {}).get('slug') == 'sold'
        
        # Create product
        product = Product(
            sku=sku,
            brand=brand,
            model=model,
            year=year,
            description=listing.get('description', ''),
            condition=condition,
            category=listing.get('categories', [{}])[0].get('full_name', '') if listing.get('categories') else '',
            base_price=price,
            status=ProductStatus.SOLD if is_sold else ProductStatus.ACTIVE
        )
        self.db.add(product)
        await self.db.flush()
        
        # Create platform_common entry
        platform_common = PlatformCommon(
            product_id=product.id,
            platform_name="reverb",
            external_id=str(listing.get('id')),
            status=ListingStatus.SOLD if is_sold else ListingStatus.ACTIVE,
            sync_status=SyncStatus.SYNCED,
            last_sync=datetime.now(),
            listing_url=listing.get('_links', {}).get('web', {}).get('href', '')
        )
        self.db.add(platform_common)
        await self.db.flush()
        
        # Create ReverbListing entry (you already have this model)
        reverb_listing = ReverbListing(
            platform_id=platform_common.id,
            reverb_listing_id=str(listing.get('id')),
            reverb_slug=listing.get('slug', ''),
            reverb_category_uuid=listing.get('categories', [{}])[0].get('uuid', '') if listing.get('categories') else '',
            condition_rating=listing.get('condition_rating', 3.5),
            inventory_quantity=listing.get('inventory', 1),
            has_inventory=listing.get('has_inventory', True),
            offers_enabled=listing.get('offers_enabled', True),
            is_auction=listing.get('auction', False),
            list_price=price,
            listing_currency=listing.get('listing_currency', 'USD'),
            reverb_state=listing.get('state', {}).get('slug', 'live'),
            created_at=datetime.now(),
            updated_at=datetime.now(),
            last_synced_at=datetime.now()
        )
        self.db.add(reverb_listing)