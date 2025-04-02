# app/services/ebay/importer.py
import os
import json
import uuid
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Union
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, AsyncConnection
from sqlalchemy import text
from dotenv import load_dotenv

from app.services.ebay.trading import EbayTradingAPI
from app.core.exceptions import EbayAPIError
from app.models.product import Product, ProductStatus, ProductCondition
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

class EbayImporter:
    """Service for importing eBay listings into the local database"""
    
    def __init__(self, db: Union[str, AsyncSession] = None):
        """
        Initialize the importer
        
        Args:
            db: Database session or URL string
                If None, will use DATABASE_URL from environment
        """
        self.trading_api = EbayTradingAPI(sandbox=False)
        self.expected_user_id = "londonvintagegts"  # Your eBay seller ID
        
        # Handle different types of db parameter
        if isinstance(db, AsyncSession):
            # If we got a session, use it directly
            self.db = db
            self.engine = None
            self.should_close_db = False
        elif isinstance(db, str) or db is None:
            # If we got a URL string or None, create an engine
            self.db_url = db or os.environ.get('DATABASE_URL')
            self.engine = create_async_engine(self.db_url, pool_recycle=3600, isolation_level="AUTOCOMMIT")
            self.db = None  # Will be created when needed
            self.should_close_db = True
        else:
            raise ValueError(f"Unexpected db parameter type: {type(db)}")
    
    async def verify_user(self) -> bool:
        """
        Verify eBay user credentials
        
        Returns:
            bool: True if authenticated with the correct user
        """
        user_info = await self.trading_api.get_user_info()
        
        if not user_info.get('success'):
            logger.error(f"Failed to get eBay user info: {user_info.get('message')}")
            return False
        
        user_id = user_info.get('user_data', {}).get('UserID')
        if user_id != self.expected_user_id:
            logger.error(f"Unexpected eBay user: {user_id}, expected: {self.expected_user_id}")
            return False
        
        logger.info(f"Successfully authenticated as eBay user: {user_id}")
        return True
    
    async def import_all_listings(self) -> Dict[str, int]:
        """
        Import all listings from eBay and create/update corresponding database records
        
        Returns:
            Dict[str, int]: Statistics about the import operation
        """
        stats = {
            "total": 0,
            "created": 0,
            "updated": 0,
            "errors": 0,
            "db_count_before": 0,
            "db_count_after": 0
        }
        
        # Check if we have db connection/engine
        if not self.engine and not self.db:
            logger.error("No database connection available")
            return stats
        
        # Verify database count before import
        stats["db_count_before"] = await self.verify_data_written()
        logger.info(f"Current database has {stats['db_count_before']} eBay listings before import")
        
        try:
            logger.info("Starting import of all eBay listings")
            
            # Verify eBay user
            if not await self.verify_user():
                logger.error("Failed to verify eBay user, canceling import")
                return stats
            
            # Get all listings from eBay (active, sold, and unsold)
            logger.info("Fetching all eBay listings (active, sold, and unsold)")
            all_listings = await self.trading_api.get_all_selling_listings(
                include_active=True,
                include_sold=True,
                include_unsold=True,
                include_details=True
            )
            
            # Process each type of listing
            listing_types = ['active', 'sold', 'unsold']
            for listing_type in listing_types:
                if listing_type in all_listings and all_listings[listing_type]:
                    listings = all_listings[listing_type]
                    logger.info(f"Processing {len(listings)} {listing_type} eBay listings")
                    
                    for i, listing in enumerate(listings):
                        # Skip None or invalid listings
                        if not listing or not isinstance(listing, dict) or 'ItemID' not in listing:
                            logger.warning(f"Skipping invalid {listing_type} listing")
                            stats["errors"] += 1
                            continue
                            
                        item_id = listing.get('ItemID')
                        logger.info(f"Processing {listing_type} eBay listing {item_id} ({i+1}/{len(listings)})")
                        
                        if not self.engine:
                            logger.error("No engine available - creating engine from DATABASE_URL")
                            self.db_url = os.environ.get('DATABASE_URL')
                            self.engine = create_async_engine(self.db_url, pool_recycle=3600, isolation_level="AUTOCOMMIT")
                        
                        try:
                            # Use the engine for proper transaction handling
                            async with self.engine.connect() as conn:
                                result = await self._process_single_listing(conn, listing, listing_type)
                                if result == "created":
                                    stats["created"] += 1
                                    logger.info(f"Created new listing for {listing_type} eBay item {item_id}")
                                elif result == "updated":
                                    stats["updated"] += 1
                                    logger.info(f"Updated listing for {listing_type} eBay item {item_id}")
                                else:
                                    stats["errors"] += 1
                                    logger.error(f"Error processing {listing_type} listing {item_id}: {result}")
                        except Exception as e:
                            stats["errors"] += 1
                            logger.exception(f"Error processing {listing_type} listing {item_id}: {str(e)}")
            
            # Update total count
            stats["total"] = stats["created"] + stats["updated"] + stats["errors"]
            
            # Verify database count after import
            stats["db_count_after"] = await self.verify_data_written()
            logger.info(f"Database now has {stats['db_count_after']} eBay listings after import")
            
            return stats
            
        except Exception as e:
            logger.exception(f"Error importing eBay listings: {str(e)}")
            return stats
    
    async def _process_single_listing(self, conn: AsyncConnection, listing: Dict[str, Any], listing_type: str = "active") -> str:
        """
        Process a single listing with its own transaction
        
        Args:
            conn: Database connection
            listing: eBay listing data
            listing_type: Type of listing ('active', 'sold', 'unsold')
            
        Returns:
            str: "created", "updated", or error message
        """
        item_id = listing.get('ItemID')
        logger.info(f"Processing eBay listing {item_id}")
        
        try:
            # Use explicit transaction
            async with conn.begin():
                # Map the eBay data to our model fields
                mapped_data = self._map_ebay_api_to_model(listing, listing_type)
                
                # Prepare data for database (convert Python objects to JSON for PostgreSQL)
                # and remove timezone information from datetime fields
                db_ready_data = self._prepare_for_db(mapped_data)
                
                # Generate SKU for this eBay item
                sku = f"EBAY-{item_id}"
                
                # Check if product exists
                product_stmt = text("SELECT id FROM products WHERE sku = :sku")
                product_result = await conn.execute(product_stmt, {"sku": sku})
                product_id = product_result.scalar()
                
                # If product doesn't exist, create it
                if not product_id:
                    # Extract product data
                    title = mapped_data.get('title', '')
                    
                    # Extract brand/model from title
                    brand = title.split(' ')[0] if title else 'Unknown'
                    model = ' '.join(title.split(' ')[1:]) if len(title.split(' ')) > 1 else title
                    
                    # Set appropriate product status based on listing type
                    status = ProductStatus.ACTIVE  # Default for all products
                    if listing_type.lower() == 'sold':
                        status = ProductStatus.SOLD
                    elif listing_type.lower() == 'unsold':
                        # For unsold items, use ACTIVE (so they can be sold elsewhere)
                        status = ProductStatus.ACTIVE  # Use ACTIVE instead of INACTIVE
                    
                    # Map condition
                    condition = ProductCondition.GOOD  # Default
                    condition_name = mapped_data.get('condition_display_name', '').lower()
                    if condition_name:
                        if 'new' in condition_name:
                            condition = ProductCondition.NEW
                        elif 'mint' in condition_name or 'excellent' in condition_name:
                            condition = ProductCondition.EXCELLENT
                        elif 'very good' in condition_name:
                            condition = ProductCondition.VERY_GOOD
                        elif 'good' in condition_name:
                            condition = ProductCondition.GOOD
                        elif 'fair' in condition_name:
                            condition = ProductCondition.FAIR
                        elif 'poor' in condition_name:
                            condition = ProductCondition.POOR
                    
                    # Extract images
                    picture_urls = mapped_data.get('picture_urls')
                    if isinstance(picture_urls, str):
                        try:
                            picture_urls = json.loads(picture_urls)
                        except:
                            picture_urls = []
                    
                    primary_image = picture_urls[0] if picture_urls and len(picture_urls) > 0 else None
                    additional_images = picture_urls[1:] if picture_urls and len(picture_urls) > 1 else []
                    
                    # Create product record
                    now = datetime.now(timezone.utc).replace(tzinfo=None)
                    product_stmt = text("""
                        INSERT INTO products (
                            sku, brand, model, description, condition, 
                            category, base_price, status, primary_image, 
                            additional_images, created_at, updated_at
                        ) VALUES (
                            :sku, :brand, :model, :description, :condition,
                            :category, :price, :status, :primary_image,
                            :additional_images, :now, :now
                        ) RETURNING id
                    """)
                    
                    product_result = await conn.execute(product_stmt, {
                        "sku": sku,
                        "brand": brand,
                        "model": model,
                        "description": mapped_data.get('listing_data', {}).get('Description', ''),
                        "condition": condition.value,
                        "category": mapped_data.get('ebay_category_name', ''),
                        "price": mapped_data.get('price', 0.0),
                        "status": status.value,
                        "primary_image": primary_image,
                        "additional_images": json.dumps(additional_images),
                        "now": now
                    })
                    
                    product_id = product_result.scalar()
                    logger.info(f"Created new product for eBay item {item_id}")
                
                # Now let's handle platform_common - but only if we have a product
                platform_id = None
                if product_id:
                    # Check if platform_common exists
                    platform_stmt = text("""
                        SELECT id FROM platform_common 
                        WHERE external_id = :item_id AND platform_name = 'ebay'
                    """)
                    platform_result = await conn.execute(platform_stmt, {"item_id": item_id})
                    platform_id = platform_result.scalar()
                    
                    # If platform_common doesn't exist, create it
                    if not platform_id:
                        # Map listing status for platform_common (keep the eBay-specific status)
                        listing_status = ListingStatus.ACTIVE
                        if listing_type.lower() == 'sold':
                            listing_status = ListingStatus.SOLD
                        elif listing_type.lower() == 'unsold':
                            listing_status = ListingStatus.INACTIVE  # This enum should have INACTIVE
                        
                        # Create platform_common record
                        now = datetime.now(timezone.utc).replace(tzinfo=None)
                        platform_stmt = text("""
                            INSERT INTO platform_common (
                                product_id, platform_name, external_id, status,
                                sync_status, last_sync, listing_url, created_at, updated_at
                            ) VALUES (
                                :product_id, 'ebay', :item_id, :status,
                                :sync_status, :now, :listing_url, :now, :now
                            ) RETURNING id
                        """)
                        
                        listing_url = mapped_data.get('listing_url') or f"https://www.ebay.com/itm/{item_id}"
                        
                        platform_result = await conn.execute(platform_stmt, {
                            "product_id": product_id,
                            "item_id": item_id,
                            "status": listing_status.value,
                            "sync_status": SyncStatus.SUCCESS.value,
                            "now": now,
                            "listing_url": listing_url
                        })
                        
                        platform_id = platform_result.scalar()
                        logger.info(f"Created new platform_common for eBay item {item_id}")
                
                # Add platform_id to db_ready_data if available
                if platform_id:
                    db_ready_data['platform_id'] = platform_id
                
                # Check if listing exists
                stmt = text("SELECT id FROM ebay_listings WHERE ebay_item_id = :item_id")
                result = await conn.execute(stmt, {"item_id": item_id})
                listing_id = result.scalar()
                
                if listing_id:
                    # This is unexpected on a clean database - log additional info
                    logger.warning(f"Item {item_id} already exists in database with ID {listing_id} - updating instead of creating")
                    
                    # You could also query for more info about the existing record
                    detail_stmt = text("SELECT ebay_item_id, title, format, updated_at FROM ebay_listings WHERE id = :id")
                    detail_result = await conn.execute(detail_stmt, {"id": listing_id})
                    existing_record = detail_result.fetchone()
                    if existing_record:
                        # Convert SQLAlchemy Row to dict properly
                        existing_dict = {key: getattr(existing_record, key) for key in existing_record._fields}
                        logger.warning(f"Existing record: {existing_dict}")
                        
                    # Update existing listing
                    update_fields = ", ".join([f"{k} = :{k}" for k in db_ready_data.keys()])
                    update_stmt = text(f"UPDATE ebay_listings SET {update_fields} WHERE id = :id")
                    
                    # Add the ID to the parameters
                    params = {**db_ready_data, "id": listing_id}
                    await conn.execute(update_stmt, params)
                    return "updated"
                else:
                    # Create new listing
                    columns = ", ".join(db_ready_data.keys())
                    placeholders = ", ".join([f":{k}" for k in db_ready_data.keys()])
                    insert_stmt = text(f"INSERT INTO ebay_listings ({columns}) VALUES ({placeholders})")
                    
                    await conn.execute(insert_stmt, db_ready_data)
                    return "created"
        except Exception as e:
            # Make sure connection is clean
            try:
                await conn.rollback()
            except:
                pass
                
            logger.exception(f"Transaction error for listing {item_id}: {str(e)}")
            return f"Error: {str(e)}"
    
    async def _create_listing(self, conn, listing: Dict[str, Any]) -> None:
        """
        Create a new eBay listing in the database
        
        Args:
            conn: Database connection or session
            listing: eBay listing data
        """
        item_id = listing.get('ItemID')
        
        # Extract price
        selling_status = listing.get('SellingStatus', {})
        price_data = selling_status.get('CurrentPrice', {})
        try:
            price = float(price_data.get('#text', '0.0'))
        except (ValueError, TypeError):
            price = 0.0
        
        # Extract quantity
        try:
            quantity = int(listing.get('QuantityAvailable', '1'))
        except (ValueError, TypeError):
            quantity = 1
        
        # Extract listing format
        listing_type = listing.get('ListingType', '')
        format_value = 'BUY_IT_NOW'
        if listing_type == 'Chinese':
            format_value = 'AUCTION'
        elif listing_type == 'FixedPriceItem':
            format_value = 'BUY_IT_NOW'
        
        # Extract category information
        primary_category = listing.get('PrimaryCategory', {})
        secondary_category = listing.get('SecondaryCategory', {})
        ebay_category_id = primary_category.get('CategoryID') if primary_category else None
        ebay_second_category_id = secondary_category.get('CategoryID') if secondary_category else None
        
        # Current timestamp
        now = datetime.now(timezone.utc)
        # Convert to timezone-naive by removing the timezone information
        now = now.replace(tzinfo=None)
        
        # Build query
        insert_query = text("""
        INSERT INTO ebay_listings (
            ebay_item_id, ebay_category_id, ebay_second_category_id, 
            format, price, quantity, listing_status, 
            created_at, updated_at, last_synced_at
        ) VALUES (
            :item_id, :category_id, :second_category_id, 
            :format, :price, :quantity, :listing_status, 
            :now, :now, :now
        )
        """)
        
        # Execute query
        await conn.execute(
            insert_query, 
            {
                "item_id": item_id,
                "category_id": ebay_category_id,
                "second_category_id": ebay_second_category_id,
                "format": format_value,
                "price": price,
                "quantity": quantity,
                "listing_status": 'ACTIVE',
                "now": now
            }
        )
        
        logger.info(f"Created new listing for eBay item {item_id}")
    
    async def _update_listing(self, conn, listing_id: int, listing: Dict[str, Any]) -> None:
        """
        Update an existing eBay listing in the database
        
        Args:
            conn: Database connection or session
            listing_id: Database ID of the existing listing
            listing: Updated eBay listing data
        """
        item_id = listing.get('ItemID')
        
        # Extract price
        selling_status = listing.get('SellingStatus', {})
        price_data = selling_status.get('CurrentPrice', {})
        try:
            price = float(price_data.get('#text', '0.0'))
        except (ValueError, TypeError):
            price = 0.0
        
        # Extract quantity
        try:
            quantity = int(listing.get('QuantityAvailable', '1'))
        except (ValueError, TypeError):
            quantity = 1
        
        # Extract listing format
        listing_type = listing.get('ListingType', '')
        format_value = 'BUY_IT_NOW'
        if listing_type == 'Chinese':
            format_value = 'AUCTION'
        elif listing_type == 'FixedPriceItem':
            format_value = 'BUY_IT_NOW'
        
        # Current timestamp
        now = datetime.now(timezone.utc)
        
        # Build query with minimal fields to reduce chance of errors
        update_query = text("""
        UPDATE ebay_listings SET
            price = :price,
            quantity = :quantity,
            format = :format,
            updated_at = :now,
            last_synced_at = :now,
            listing_status = :listing_status
        WHERE id = :id
        """)
        
        # Execute query
        await conn.execute(
            update_query, 
            {
                "id": listing_id,
                "price": price,
                "quantity": quantity,
                "format": format_value,
                "now": now,
                "listing_status": 'ACTIVE'
            }
        )
        
        logger.info(f"Updated listing for eBay item {item_id}")
        
    async def verify_data_written(self) -> int:
        """
        Verify that data was actually written to the database
        
        Returns:
            int: Number of records found in the database
        """
        try:
            if self.engine:
                # Use direct connection if we have an engine
                async with self.engine.connect() as conn:
                    result = await conn.execute(text("SELECT COUNT(*) FROM ebay_listings"))
                    count = result.scalar()
                    return count
            elif self.db:
                # Use provided session
                result = await self.db.execute(text("SELECT COUNT(*) FROM ebay_listings"))
                count = result.scalar()
                return count
            else:
                return 0
        except Exception as e:
            logger.exception(f"Error verifying data written: {str(e)}")
            return 0
        
    def _map_ebay_api_to_model(self, listing: Dict[str, Any], listing_type: str = "active") -> Dict[str, Any]:
        """
        Map eBay API data to EbayListing model fields
        
        Args:
            listing: eBay listing data from API
            listing_type: Type of listing ('active', 'sold', 'unsold')
            
        Returns:
            Dict with mapped fields matching EbayListing model
        """
        # Ensure listing is not None
        if listing is None:
            logger.error(f"Received None listing for type {listing_type}")
            return {
                "ebay_item_id": f"error-{uuid.uuid4()}",
                "listing_status": "ERROR",
                "title": f"Error - None listing for {listing_type}",
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
                "last_synced_at": datetime.now(timezone.utc)
            }
        
        # Initialize the mapped data with default values
        mapped_data = {
            "ebay_item_id": listing.get("ItemID", f"unknown-{uuid.uuid4()}"),
            "listing_status": listing_type.upper(),
            "title": listing.get("Title", ""),
            
            # Parse format (ListingType)
            "format": "BUY_IT_NOW" if listing.get("ListingType") in ["FixedPriceItem", "StoreInventory"] else "AUCTION",
            
            # Parse price - safely handle the nested gets
            "price": 0.0,  # Default value
            
            # Parse quantities - use safe defaults
            "quantity": 0,
            "quantity_available": 0,
            "quantity_sold": 0,
            
            # Parse categories - safe defaults
            "ebay_category_id": None,
            "ebay_category_name": None,
            "ebay_second_category_id": None,
            
            # Parse dates/times
            "start_time": None,
            "end_time": None,
            
            # Parse URLs
            "listing_url": None,
            
            # Parse condition information
            "ebay_condition_id": None,
            "condition_display_name": None,
            
            # Parse image URLs
            "gallery_url": None,
            "picture_urls": [],
            
            # Parse item specifics as JSON
            "item_specifics": {},
            
            # Store policy IDs
            "payment_policy_id": None,
            "return_policy_id": None,
            "shipping_policy_id": None,
            
            # Store transaction data for sold items
            "transaction_id": None,
            "order_line_item_id": None,
            "buyer_user_id": None,
            "paid_time": None,
            "payment_status": None,
            
            # Store current timestamp for tracking purposes
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "last_synced_at": datetime.now(timezone.utc),
            
            # Store the original listing data as JSON for reference
            "listing_data": {
                "Title": listing.get("Title"),
                "ItemID": listing.get("ItemID"),
                "Country": listing.get("Country"),
                "_listing_type": listing_type
            }
        }
        
        # Now safely add data that might be nested
        try:
            # Price - safe extraction with nested gets
            selling_status = listing.get("SellingStatus", {})
            if selling_status:
                current_price = selling_status.get("CurrentPrice", {})
                if current_price and isinstance(current_price, dict):
                    price_text = current_price.get("#text")
                    if price_text:
                        try:
                            mapped_data["price"] = float(price_text)
                        except (ValueError, TypeError):
                            pass
                # Handle quantities
                if selling_status:
                    quantity_sold_str = selling_status.get("QuantitySold")
                    if quantity_sold_str:
                        try:
                            mapped_data["quantity_sold"] = int(quantity_sold_str)
                        except (ValueError, TypeError):
                            pass
                            
            # Quantities
            quantity_str = listing.get("Quantity")
            if quantity_str:
                try:
                    mapped_data["quantity"] = int(quantity_str)
                except (ValueError, TypeError):
                    pass
                    
            quantity_available_str = listing.get("QuantityAvailable")
            if quantity_available_str:
                try:
                    mapped_data["quantity_available"] = int(quantity_available_str)
                except (ValueError, TypeError):
                    pass
    
            # Categories - using direct access as discovered in the notebook
            mapped_data["ebay_category_id"] = listing.get("PrimaryCategoryID")
            mapped_data["ebay_category_name"] = listing.get("PrimaryCategoryName")
                
            secondary_category = listing.get("SecondaryCategory", {})
            if secondary_category:
                mapped_data["ebay_second_category_id"] = secondary_category.get("CategoryID")
            
            # Dates/Times
            listing_details = listing.get("ListingDetails", {})
            if listing_details:
                mapped_data["start_time"] = self._parse_ebay_datetime(listing_details.get("StartTime"))
                mapped_data["end_time"] = self._parse_ebay_datetime(listing_details.get("EndTime"))
                mapped_data["listing_url"] = listing_details.get("ViewItemURL")
            
            # Condition
            mapped_data["ebay_condition_id"] = listing.get("ConditionID")
            mapped_data["condition_display_name"] = listing.get("ConditionDisplayName")
            
            # Extract gallery and picture information - with better None handling
            picture_details = listing.get("PictureDetails")
            if picture_details is None:
                picture_details = {}
            
            mapped_data["gallery_url"] = picture_details.get("GalleryURL")
            
            picture_urls = picture_details.get("PictureURL", [])
            if picture_urls is None:
                picture_urls = []
            elif not isinstance(picture_urls, list):
                picture_urls = [picture_urls]
            mapped_data["picture_urls"] = picture_urls
            
            # Item specifics with better error handling
            if "ItemSpecifics" in listing and listing["ItemSpecifics"] is not None:
                item_specifics = self._extract_item_specifics(listing)
                if item_specifics:
                    mapped_data["item_specifics"] = item_specifics
            
            # Seller profiles
            seller_profiles = listing.get("SellerProfiles", {})
            if seller_profiles:
                payment_profile = seller_profiles.get("SellerPaymentProfile", {})
                if payment_profile:
                    mapped_data["payment_policy_id"] = payment_profile.get("PaymentProfileID")
                    
                return_profile = seller_profiles.get("SellerReturnProfile", {})
                if return_profile:
                    mapped_data["return_policy_id"] = return_profile.get("ReturnProfileID")
                    
                shipping_profile = seller_profiles.get("SellerShippingProfile", {})
                if shipping_profile:
                    mapped_data["shipping_policy_id"] = shipping_profile.get("ShippingProfileID")
            
            # Transaction data with better error handling
            transaction = listing.get("Transaction", {})
            if transaction:
                mapped_data["transaction_id"] = transaction.get("TransactionID")
                mapped_data["order_line_item_id"] = transaction.get("OrderLineItemID")
    
                buyer = transaction.get("Buyer", {})
                if buyer:
                    mapped_data["buyer_user_id"] = buyer.get("UserID")
    
                mapped_data["paid_time"] = self._parse_ebay_datetime(transaction.get("PaidTime"))
                mapped_data["payment_status"] = transaction.get("SellerPaidStatus")
    
        except Exception as e:
            logger.exception(f"Error mapping eBay data for item {listing.get('ItemID')}: {str(e)}")
            # We'll still return the basic mapped data even if some parts failed
    
        # For sold or unsold listings, add shipping status
        if listing_type in ["sold", "unsold"]:
            try:
                transaction = listing.get("Transaction", {})
                if transaction and transaction.get("SellerPaidStatus") == "Paid":
                    mapped_data["shipping_status"] = "READY_TO_SHIP"
                else:
                    mapped_data["shipping_status"] = "PENDING_PAYMENT"
            except Exception:
                mapped_data["shipping_status"] = "PENDING_PAYMENT"
    
        return mapped_data

    def _parse_ebay_datetime(self, dt_str: Optional[str]) -> Optional[datetime]:
        """Parse eBay datetime string to Python datetime object"""
        if not dt_str:
            return None
        
        try:
            # Handle ISO format datetime strings
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            try:
                # Fallback to more flexible parsing
                return datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S.%fZ")
            except (ValueError, TypeError):
                logger.warning(f"Could not parse datetime: {dt_str}")
                return None
    
    def _prepare_for_db(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare data for database insertion by converting Python objects to JSON strings
        and removing timezone information from datetime fields
        
        Args:
            data: Dictionary with data to be prepared for database insertion
            
        Returns:
            Dict with data ready for database insertion
        """
        result = data.copy()
        
        # Convert list/dict fields to JSON strings for PostgreSQL JSONB columns
        for field in ['picture_urls', 'item_specifics', 'listing_data']:
            if field in result and result[field] is not None:
                try:
                    result[field] = json.dumps(result[field], default=str)
                except (TypeError, ValueError) as e:
                    logger.warning(f"Error converting {field} to JSON: {str(e)}")
                    # If conversion fails, store as empty JSON object or array
                    if field == 'picture_urls':
                        result[field] = '[]'
                    else:
                        result[field] = '{}'
        
        # Remove timezone information from all datetime fields
        # since DB uses timestamp without time zone
        for field in ['start_time', 'end_time', 'paid_time', 'created_at', 'updated_at', 'last_synced_at']:
            if field in result and result[field] is not None:
                # If the datetime has timezone, remove it
                if hasattr(result[field], 'tzinfo') and result[field].tzinfo is not None:
                    result[field] = result[field].replace(tzinfo=None)
        
        return result
    
    def _extract_item_specifics(self, listing: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract item specifics from eBay listing data
        
        Args:
            listing: eBay listing data
            
        Returns:
            Dict with item specifics
        """
        result = {}
        
        try:
            # Extract from ItemSpecifics structure
            item_specifics = listing.get("ItemSpecifics", {})
            if not item_specifics:
                return result
                
            name_value_list = item_specifics.get("NameValueList")
            if not name_value_list:
                return result
                
            # Sometimes this is a list, sometimes a single dict
            if isinstance(name_value_list, list):
                for item in name_value_list:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("Name")
                    value = item.get("Value")
                    if name and value:
                        result[name] = value
            elif isinstance(name_value_list, dict):
                name = name_value_list.get("Name")
                value = name_value_list.get("Value")
                if name and value:
                    result[name] = value
        except Exception as e:
            logger.exception(f"Error extracting item specifics: {str(e)}")
            
        return result
    
    async def recreate_ebay_listings_table(self) -> bool:
        """
        Drop and recreate the ebay_listings table
        
        Returns:
            bool: True if successful
        """
        try:
            async with self.engine.begin() as conn:
                # Drop table if exists
                await conn.execute(text("DROP TABLE IF EXISTS ebay_listings"))
                
                # Create new table with platform_id column
                create_table_sql = """
                CREATE TABLE ebay_listings (
                    id SERIAL PRIMARY KEY,
                    platform_id INTEGER,
                    ebay_item_id VARCHAR UNIQUE,
                    listing_status VARCHAR,
                    title VARCHAR,
                    format VARCHAR,
                    price FLOAT,
                    quantity INTEGER,
                    quantity_available INTEGER,
                    quantity_sold INTEGER DEFAULT 0,
                    ebay_category_id VARCHAR,
                    ebay_category_name VARCHAR,
                    ebay_second_category_id VARCHAR,
                    start_time TIMESTAMP,
                    end_time TIMESTAMP,
                    listing_url VARCHAR,
                    ebay_condition_id VARCHAR,
                    condition_display_name VARCHAR,
                    gallery_url VARCHAR,
                    picture_urls JSONB,
                    item_specifics JSONB,
                    payment_policy_id VARCHAR,
                    return_policy_id VARCHAR,
                    shipping_policy_id VARCHAR,
                    transaction_id VARCHAR,
                    order_line_item_id VARCHAR,
                    buyer_user_id VARCHAR,
                    paid_time TIMESTAMP,
                    payment_status VARCHAR,
                    shipping_status VARCHAR,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    listing_data JSONB,
                    FOREIGN KEY (platform_id) REFERENCES platform_common(id) ON DELETE SET NULL
                )
                """
                await conn.execute(text(create_table_sql))
                
                # Create indexes
                await conn.execute(text("CREATE INDEX idx_ebay_listings_ebay_item_id ON ebay_listings(ebay_item_id)"))
                await conn.execute(text("CREATE INDEX idx_ebay_listings_listing_status ON ebay_listings(listing_status)"))
                await conn.execute(text("CREATE INDEX idx_ebay_listings_ebay_category_id ON ebay_listings(ebay_category_id)"))
                await conn.execute(text("CREATE INDEX idx_ebay_listings_platform_id ON ebay_listings(platform_id)"))
                
                logger.info("Successfully recreated ebay_listings table")
                return True
                
        except Exception as e:
            logger.exception(f"Error recreating ebay_listings table: {str(e)}")
            return False
        
    def _convert_to_naive_datetime(self, dt):
        """Convert a timezone-aware datetime to a naive datetime for PostgreSQL"""
        if dt is None:
            return None
        
        # If datetime has timezone info, convert to UTC and remove timezone
        if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
            return dt.replace(tzinfo=None)
        return dt