# app/services/ebay_service.py

import logging
import asyncio
import json
from typing import Optional, Dict, List, Any, Union, Tuple
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy import select, update, delete

from app.models.ebay import EbayListing
from app.models.product import Product, ProductCondition, ProductStatus
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.schemas.platform.ebay import EbayListingCreate
from app.core.config import Settings
from app.core.enums import EbayListingStatus
from app.core.exceptions import EbayAPIError, ListingNotFoundError, DatabaseError
from app.services.ebay.client import EbayClient
from app.services.ebay.trading import EbayTradingLegacyAPI

logger = logging.getLogger(__name__)

class EbayService:
    """
    Service for managing eBay listings and synchronization.
    
    Focused on importing FROM eBay to detect sales and keep our system updated.
    """
    
    def __init__(self, db: AsyncSession, settings: Settings = None):
        """Initialize the eBay service with database session and settings"""
        self.db = db
        self.settings = settings
        
        # Use settings to determine sandbox mode, default to production
        sandbox_mode = settings.EBAY_SANDBOX_MODE if settings else False
        
        # Initialize API clients
        self.trading_api = EbayTradingLegacyAPI(sandbox=sandbox_mode)
        
        # Default user expected for verification
        self.expected_user_id = "londonvintagegts"
    
    # -------------------------------------------------------------------------
    # Main Sync Methods (FROM eBay)
    # -------------------------------------------------------------------------
    
    async def sync_inventory_from_ebay(self, progress_callback=None) -> Dict[str, int]:
        """
        Synchronize all eBay inventory to database with optional progress reporting
        Returns: Dict with statistics about the sync operation
        """
        
        # Initialize result stats
        results = {
            "total": 0,
            "created": 0,
            "updated": 0,
            "errors": 0,
            "marked_sold": 0
        }
        
        try:
            logger.info("=== STARTING EBAY SYNC ===")
            print("=== STARTING EBAY SYNC ===")
            # Send initial progress
            if progress_callback:
                await progress_callback({
                    "message": "Starting eBay sync...",
                    "progress": 0,
                    "total": 0,
                    "processed": 0
                })
            
            # Verify eBay user
            if progress_callback:
                await progress_callback({
                    "message": "Verifying eBay credentials...",
                    "progress": 10,
                    "total": 0,
                    "processed": 0
                })
            
            logger.info("About to verify eBay credentials...")
            print("About to verify eBay credentials...")
            if not await self.verify_credentials():
                logger.error("Failed to verify eBay user, canceling sync")
                if progress_callback:
                    await progress_callback({
                        "error": "Failed to verify eBay credentials",
                        "message": "Authentication failed"
                    })
                return results

            logger.info("eBay credentials verified successfully") 
            print("*** eBay credentials verified successfully ***")
            # Get all listings from eBay (active, sold, unsold)
            if progress_callback:
                await progress_callback({
                    "message": "Fetching eBay listings...",
                    "progress": 20,
                    "total": 0,
                    "processed": 0
                })
                
            logger.info("Fetching all eBay listings (active, sold, unsold)")
            print("*** ABOUT TO FETCH ALL eBay LISTINGS ***")
            all_listings = await self.trading_api.get_all_selling_listings(
                include_active=True,
                include_sold=True,
                include_unsold=True,
                include_details=True
            )
            print("*** FINISHED FETCHING ALL eBay LISTINGS ***")
            import time
            time.sleep(20)
            # Count total listings
            total_listings = 0
            for listing_type in ['active', 'sold', 'unsold']:
                if listing_type in all_listings:
                    total_listings += len(all_listings.get(listing_type, []))
            
            results["total"] = total_listings
            
            if progress_callback:
                await progress_callback({
                    "message": f"Processing {total_listings} eBay listings...",
                    "progress": 30,
                    "total": total_listings,
                    "processed": 0
                })

            logger.info(f"Processing {total_listings} eBay listings")
            
            # Process each type of listing
            created_count = 0
            updated_count = 0
            error_count = 0
            marked_sold_count = 0
            processed_count = 0
            
            listing_types = ['active', 'sold', 'unsold']
            for listing_type in listing_types:
                if listing_type not in all_listings:
                    continue
                    
                listings = all_listings[listing_type]
                logger.info(f"Processing {len(listings)} {listing_type} eBay listings")
                
                for idx, listing in enumerate(listings):
                    try:
                        # Skip invalid listings
                        if not listing or not isinstance(listing, dict) or 'ItemID' not in listing:
                            logger.warning(f"Skipping invalid {listing_type} listing")
                            error_count += 1
                            continue
                        
                        item_id = listing.get('ItemID')
                        
                        # Check if listing exists in database
                        query = select(EbayListing).where(EbayListing.ebay_item_id == item_id)
                        result = await self.db.execute(query)
                        existing_listing = result.scalar_one_or_none()
                        
                        if existing_listing:
                            # Update existing listing
                            update_result = await self._update_listing_from_api_data(
                                existing_listing, listing, listing_type
                            )
                            if update_result == "updated":
                                updated_count += 1
                            elif update_result == "marked_sold":
                                marked_sold_count += 1
                            else:
                                error_count += 1
                        else:
                            # Create new listing
                            create_result = await self._create_listing_from_api_data(listing, listing_type)
                            if create_result:
                                created_count += 1
                            else:
                                error_count += 1
                        
                        processed_count += 1
                        
                        # Send progress update every 10 items
                        if processed_count % 10 == 0 and progress_callback:
                            progress = 30 + (processed_count / total_listings) * 60
                            await progress_callback({
                                "message": f"Processed {processed_count}/{total_listings} listings...",
                                "progress": int(progress),
                                "total": total_listings,
                                "processed": processed_count
                            })
                            
                    except Exception as e:
                        logger.exception(f"Error processing {listing_type} listing {listing.get('ItemID')}: {str(e)}")
                        error_count += 1
                        processed_count += 1
            
            # Update final results
            results["created"] = created_count
            results["updated"] = updated_count
            results["errors"] = error_count
            results["marked_sold"] = marked_sold_count

            # Always send completion notification
            if progress_callback:
                await progress_callback({
                    "message": f"eBay sync complete! Created: {created_count}, Updated: {updated_count}, Sold: {marked_sold_count}, Errors: {error_count}",
                    "progress": 100,
                    "total": total_listings,
                    "processed": total_listings,
                    "completed": True,
                    "stats": results
                })

            # Log completion
            logger.info(f"eBay sync completed. Created: {created_count}, Updated: {updated_count}, Sold: {marked_sold_count}, Errors: {error_count}")

            return results
            
        except Exception as e:
            logger.error(f"Error in eBay inventory sync: {str(e)}")
            if progress_callback:
                await progress_callback({
                    "error": str(e),
                    "message": "eBay sync failed"
                })
            raise
    
    # -------------------------------------------------------------------------
    # Create/Update Methods (FROM eBay API Data)
    # -------------------------------------------------------------------------
    
    async def _create_listing_from_api_data(self, listing: Dict[str, Any], listing_type: str = "active") -> bool:
        """
        Create a new EbayListing and associated Product from API data
        
        Args:
            listing: Listing data from eBay API
            listing_type: Type of listing ('active', 'sold', 'unsold')
            
        Returns:
            bool: True if successful, False otherwise
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        item_id = listing.get('ItemID')
        
        try:
            # Extract basic listing data
            title = listing.get('Title', '')
            
            # Extract price with proper error handling
            selling_status = listing.get('SellingStatus', {})
            price_data = selling_status.get('CurrentPrice', {})
            try:
                price = float(price_data.get('#text', '0')) if price_data else 0.0
            except (ValueError, TypeError):
                price = 0.0
            
            # Extract quantities with proper error handling
            try:
                quantity = int(listing.get('Quantity', '1'))
            except (ValueError, TypeError):
                quantity = 1
                
            try:
                quantity_available = int(listing.get('QuantityAvailable', quantity))
            except (ValueError, TypeError):
                quantity_available = quantity
                
            try:
                quantity_sold = int(selling_status.get('QuantitySold', '0'))
            except (ValueError, TypeError):
                quantity_sold = 0
            
            # Generate SKU
            sku = f"EB-{item_id}"
            
            # Extract brand/model from title for Product creation
            brand = title.split(' ')[0] if title else 'Unknown'
            model = ' '.join(title.split(' ')[1:]) if len(title.split(' ')) > 1 else title
            
            # Check if product already exists
            query = select(Product).where(Product.sku == sku)
            result = await self.db.execute(query)
            product = result.scalar_one_or_none()
            
            if not product:
                # Extract category for Product
                primary_category = listing.get('PrimaryCategory', {})
                category_name = primary_category.get('CategoryName', 'Uncategorized')
                
                # Map eBay condition to ProductCondition
                condition = ProductCondition.VERYGOOD  # Default
                ebay_condition = listing.get('ConditionDisplayName', '').lower()
                if 'new' in ebay_condition:
                    condition = ProductCondition.NEW
                elif 'excellent' in ebay_condition:
                    condition = ProductCondition.EXCELLENT
                elif 'very good' in ebay_condition:
                    condition = ProductCondition.VERYGOOD
                elif 'good' in ebay_condition:
                    condition = ProductCondition.GOOD
                elif 'fair' in ebay_condition:
                    condition = ProductCondition.FAIR
                elif 'poor' in ebay_condition:
                    condition = ProductCondition.POOR
                
                # Extract images for Product
                picture_details = listing.get('PictureDetails', {})
                picture_urls = picture_details.get('PictureURL', [])
                if not isinstance(picture_urls, list):
                    picture_urls = [picture_urls] if picture_urls else []
                
                primary_image = picture_urls[0] if picture_urls else None
                additional_images = picture_urls[1:] if len(picture_urls) > 1 else []
                
                # Set product status based on listing type
                product_status = ProductStatus.ACTIVE
                if listing_type.lower() == 'sold':
                    product_status = ProductStatus.SOLD
                
                # Create new product
                product = Product(
                    sku=sku,
                    brand=brand,
                    model=model,
                    category=category_name,
                    description=listing.get('Description', ''),
                    condition=condition,
                    status=product_status,
                    base_price=price,
                    primary_image=primary_image,
                    additional_images=json.dumps(additional_images),
                    created_at=now,
                    updated_at=now
                )
                self.db.add(product)
                await self.db.flush()  # Get product ID without committing
            
            # Create platform_common record
            platform_status = 'active'
            if listing_type.lower() == 'sold':
                platform_status = 'sold'
            elif listing_type.lower() == 'unsold':
                platform_status = 'inactive'
            
            platform_common = PlatformCommon(
                product_id=product.id,
                platform_name='ebay',
                external_id=item_id,
                status=platform_status,
                sync_status='success',
                created_at=now,
                updated_at=now
            )
            self.db.add(platform_common)
            await self.db.flush()  # Get platform_common ID
            
            # Extract detailed data for eBay listing
            ebay_listing_data = self._extract_ebay_listing_data(listing, listing_type)
            ebay_listing_data.update({
                'platform_id': platform_common.id,
                'ebay_item_id': item_id,
                'title': title,
                'price': price,
                'quantity': quantity,
                'quantity_available': quantity_available,
                'quantity_sold': quantity_sold,
                'listing_status': platform_status,
                'created_at': now,
                'updated_at': now,
                'last_synced_at': now,
                'listing_data': json.dumps(listing)  # Store complete API response
            })
            
            # Create eBay listing
            ebay_listing = EbayListing(**ebay_listing_data)
            self.db.add(ebay_listing)
            
            # Commit all changes
            await self.db.commit()
            
            logger.info(f"Successfully created eBay listing for item {item_id}")
            return True
            
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error creating listing from API data for item {item_id}: {str(e)}")
            logger.exception("Full traceback:")
            return False
    
    async def _update_listing_from_api_data(self, existing_listing: EbayListing, listing: Dict[str, Any], listing_type: str) -> str:
        """
        Update an existing EbayListing from API data
        
        Args:
            existing_listing: Existing EbayListing record
            listing: Updated listing data from eBay API
            listing_type: Type of listing ('active', 'sold', 'unsold')
            
        Returns:
            str: "updated", "marked_sold", or "error"
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        item_id = listing.get('ItemID')
        
        try:
            # Extract basic data
            price = float(listing.get('SellingStatus', {}).get('CurrentPrice', {}).get('#text', '0'))
            quantity = int(listing.get('Quantity', existing_listing.quantity or 1))
            quantity_available = int(listing.get('QuantityAvailable', quantity))
            quantity_sold = int(listing.get('SellingStatus', {}).get('QuantitySold', '0'))
            
            # Check if item was sold
            was_sold = (listing_type.lower() == 'sold' or 
                       quantity_available == 0 or 
                       listing.get('SellingStatus', {}).get('ListingStatus') == 'Completed')
            
            # Update listing fields
            existing_listing.price = price
            existing_listing.quantity = quantity
            existing_listing.quantity_available = quantity_available
            existing_listing.quantity_sold = quantity_sold
            existing_listing.updated_at = now
            existing_listing.last_synced_at = now
            
            # Update status based on listing type
            if was_sold:
                existing_listing.listing_status = 'sold'
                # Also need to update platform_common and product
                result = await self._mark_item_as_sold(existing_listing.platform_id)
                if result:
                    await self.db.commit()
                    logger.info(f"Marked eBay item {item_id} as SOLD")
                    return "marked_sold"
            else:
                existing_listing.listing_status = 'active' if listing_type == 'active' else 'inactive'
            
            # Update other fields from extracted data
            extracted_data = self._extract_ebay_listing_data(listing, listing_type)
            for field, value in extracted_data.items():
                if hasattr(existing_listing, field) and field not in ['platform_id', 'ebay_item_id', 'created_at']:
                    setattr(existing_listing, field, value)
            
            # Update complete listing data
            existing_listing.listing_data = json.dumps(listing)
            
            # Commit changes
            await self.db.commit()
            
            return "updated"
            
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error updating listing from API data for item {item_id}: {str(e)}")
            return "error"
    
    async def _mark_item_as_sold(self, platform_id: int) -> bool:
        """
        Mark an item as sold across Product and PlatformCommon
        
        Args:
            platform_id: ID of the platform_common record
            
        Returns:
            bool: True if successful
        """
        try:
            # Get platform_common record
            query = select(PlatformCommon).where(PlatformCommon.id == platform_id)
            result = await self.db.execute(query)
            platform_common = result.scalar_one_or_none()
            
            if not platform_common:
                logger.error(f"Platform record not found for ID {platform_id}")
                return False
            
            # Update platform_common status
            platform_common.status = 'sold'
            platform_common.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            
            # Get and update product status
            product_query = select(Product).where(Product.id == platform_common.product_id)
            product_result = await self.db.execute(product_query)
            product = product_result.scalar_one_or_none()
            
            if product:
                product.status = ProductStatus.SOLD
                product.is_sold = True
                product.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            
            return True
            
        except Exception as e:
            logger.error(f"Error marking item as sold: {str(e)}")
            return False
    
    def _extract_ebay_listing_data(self, listing: Dict[str, Any], listing_type: str) -> Dict[str, Any]:
        """
        Extract all relevant eBay-specific data from API response
        
        Args:
            listing: eBay API response data
            listing_type: Type of listing ('active', 'sold', 'unsold')
            
        Returns:
            Dict with eBay listing fields
        """
        # Initialize result dict
        extracted = {}
        
        # Extract category data
        primary_category = listing.get('PrimaryCategory', {})
        extracted['ebay_category_id'] = primary_category.get('CategoryID')
        extracted['ebay_category_name'] = primary_category.get('CategoryName')
        
        secondary_category = listing.get('SecondaryCategory', {})
        extracted['ebay_second_category_id'] = secondary_category.get('CategoryID')
        
        # Extract condition
        extracted['ebay_condition_id'] = listing.get('ConditionID')
        extracted['condition_display_name'] = listing.get('ConditionDisplayName')
        
        # Extract format
        listing_type_api = listing.get('ListingType', '')
        if listing_type_api == 'Chinese':
            extracted['format'] = 'AUCTION'
        elif listing_type_api in ['FixedPriceItem', 'StoreInventory']:
            extracted['format'] = 'BUY_IT_NOW'
        else:
            extracted['format'] = listing_type_api.upper()
        
        # Extract dates with timezone handling
        listing_details = listing.get('ListingDetails', {})
        if listing_details:
            extracted['start_time'] = self._parse_ebay_datetime(listing_details.get('StartTime'))
            extracted['end_time'] = self._parse_ebay_datetime(listing_details.get('EndTime'))
            extracted['listing_url'] = listing_details.get('ViewItemURL')
        
        # Extract image data
        picture_details = listing.get('PictureDetails', {})
        if picture_details:
            extracted['gallery_url'] = picture_details.get('GalleryURL')
            
            picture_urls = picture_details.get('PictureURL', [])
            if not isinstance(picture_urls, list):
                picture_urls = [picture_urls] if picture_urls else []
            extracted['picture_urls'] = json.dumps(picture_urls)
        
        # Extract item specifics
        item_specifics = self._extract_item_specifics(listing)
        if item_specifics:
            extracted['item_specifics'] = json.dumps(item_specifics)
        
        # Extract business policies
        seller_profiles = listing.get('SellerProfiles', {})
        if seller_profiles:
            payment_profile = seller_profiles.get('SellerPaymentProfile', {})
            if payment_profile:
                extracted['payment_policy_id'] = payment_profile.get('PaymentProfileID')
                
            return_profile = seller_profiles.get('SellerReturnProfile', {})
            if return_profile:
                extracted['return_policy_id'] = return_profile.get('ReturnProfileID')
                
            shipping_profile = seller_profiles.get('SellerShippingProfile', {})
            if shipping_profile:
                extracted['shipping_policy_id'] = shipping_profile.get('ShippingProfileID')
        
        # Extract transaction data for sold items
        if listing_type.lower() == 'sold':
            transaction = listing.get('Transaction', {})
            if transaction:
                extracted['transaction_id'] = transaction.get('TransactionID')
                extracted['order_line_item_id'] = transaction.get('OrderLineItemID')
                
                buyer = transaction.get('Buyer', {})
                if buyer:
                    extracted['buyer_user_id'] = buyer.get('UserID')
                
                extracted['paid_time'] = self._parse_ebay_datetime(transaction.get('PaidTime'))
                extracted['payment_status'] = transaction.get('SellerPaidStatus')
                
                # Determine shipping status
                if transaction.get('SellerPaidStatus') == 'Paid':
                    extracted['shipping_status'] = 'READY_TO_SHIP'
                else:
                    extracted['shipping_status'] = 'PENDING_PAYMENT'
        
        return extracted
    
    def _parse_ebay_datetime(self, dt_str: Optional[str]) -> Optional[datetime]:
        """Parse eBay datetime string to Python datetime object (timezone-naive)"""
        if not dt_str:
            return None
        
        try:
            # Handle ISO format datetime strings
            dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            return dt.replace(tzinfo=None)  # Make timezone-naive for PostgreSQL
        except (ValueError, TypeError):
            try:
                # Fallback to more flexible parsing
                dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S.%fZ")
                return dt.replace(tzinfo=None)
            except (ValueError, TypeError):
                logger.warning(f"Could not parse datetime: {dt_str}")
                return None
    
    def _extract_item_specifics(self, listing: Dict[str, Any]) -> Dict[str, Any]:
        """Extract item specifics from eBay listing data"""
        result = {}
        
        try:
            item_specifics = listing.get("ItemSpecifics", {})
            if not item_specifics:
                return result
                
            name_value_list = item_specifics.get("NameValueList")
            if not name_value_list:
                return result
                
            # Handle both single dict and list of dicts
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
    
    # -------------------------------------------------------------------------
    # API Wrapper Methods
    # -------------------------------------------------------------------------
    
    async def verify_credentials(self) -> bool:
        """
        Verify eBay credentials and check user ID
        
        Returns:
            bool: True if credentials are valid and user ID matches expected
        """
        try:
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
            
        except Exception as e:
            logger.error(f"Error verifying eBay credentials: {str(e)}")
            return False
    
    async def get_all_active_listings(self, include_details: bool = False) -> List[Dict[str, Any]]:
        """
        Get all active eBay listings
        
        Args:
            include_details: Whether to include full item details
            
        Returns:
            List of active listings data
        """
        return await self.trading_api.get_all_active_listings(include_details=include_details)
    
    async def get_active_listing_count(self) -> int:
        """
        Get count of active eBay listings
        
        Returns:
            int: Count of active listings
        """
        return await self.trading_api.get_total_active_listings_count()
    
    # -------------------------------------------------------------------------
    # Placeholder for TO eBay Methods (Future Implementation)
    # -------------------------------------------------------------------------
    
    async def sync_inventory_to_ebay(self) -> Dict[str, int]:
        """
        Placeholder for future implementation of syncing TO eBay
        
        This will handle cross-platform inventory sync when items are sold
        on other platforms and need to be updated on eBay.
        """
        logger.info("sync_inventory_to_ebay - placeholder for future implementation")
        return {
            "total": 0,
            "updated": 0,
            "errors": 0,
            "message": "Not yet implemented - coming soon!"
        }