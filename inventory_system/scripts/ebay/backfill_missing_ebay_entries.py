#!/usr/bin/env python3
"""
Backfill missing eBay database entries for listings that were created but not properly recorded.

This script is useful when:
- An eBay listing was created successfully but the database wasn't updated
- You need to import existing eBay listings into the system
- Database entries are missing or incomplete for existing eBay listings

Usage:
    python scripts/ebay/backfill_missing_ebay_entries.py <ebay_item_id>[:<sku>] [<ebay_item_id>[:<sku>] ...]
    
Examples:
    # Backfill with known SKU (recommended - most reliable):
    python scripts/ebay/backfill_missing_ebay_entries.py 257103228811:REV-91978750
    
    # Backfill without SKU (script will try to find it from eBay API):
    python scripts/ebay/backfill_missing_ebay_entries.py 257103123225
    
    # Backfill multiple listings at once:
    python scripts/ebay/backfill_missing_ebay_entries.py 257103123225:REV-91978762 257103228811:REV-91978750
    
    # Mix of with and without SKUs:
    python scripts/ebay/backfill_missing_ebay_entries.py 257103123225 257103228811:REV-91978750

What this script does:
1. Fetches the listing details from eBay API
2. Uses the provided SKU (or tries to extract it from eBay data) to find the product
3. Creates/updates platform_common entry with:
   - listing_url (https://www.ebay.co.uk/itm/{item_id})
   - platform_specific_data (backfill info, sandbox flag, etc.)
4. Creates/updates ebay_listings entry with all fields:
   - Category ID and name
   - Picture URLs and gallery URL
   - Condition ID and display name
   - Start/end times
   - Business policy IDs
   - And more...

Note: If eBay doesn't have the SKU field populated, you MUST provide it in the format
      item_id:sku for the script to work correctly.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
import argparse

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.database import async_session
from app.models.product import Product
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.models.ebay import EbayListing
from app.services.ebay.trading import EbayTradingLegacyAPI
from app.core.config import Settings
from sqlalchemy import select, and_
from sqlalchemy.orm import joinedload
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def get_listing_from_ebay(item_id: str, trading_api: EbayTradingLegacyAPI) -> dict:
    """Fetch listing details from eBay API."""
    try:
        response = await trading_api.get_item(item_id)
        logger.info(f"API Response keys: {list(response.keys()) if response else 'None'}")
        
        # The response might be wrapped in GetItemResponse
        if response and 'GetItemResponse' in response:
            response = response['GetItemResponse']
            logger.info(f"Unwrapped GetItemResponse keys: {list(response.keys())}")
        
        if response and "Item" in response:
            item = response["Item"]
            logger.info(f"Item data keys: {list(item.keys())[:20]}")  # Show first 20 keys
            
            # Log SKU-related fields for debugging
            logger.info(f"SKU field: {item.get('SKU', 'NOT FOUND')}")
            logger.info(f"CustomLabel field: {item.get('CustomLabel', 'NOT FOUND')}")
            
            # Extract price - eBay returns prices as dict with #text key
            price = 0
            if 'CurrentPrice' in item:
                if isinstance(item['CurrentPrice'], dict) and '#text' in item['CurrentPrice']:
                    price = float(item['CurrentPrice']['#text'])
                else:
                    price = float(item['CurrentPrice'])
            elif 'StartPrice' in item:
                if isinstance(item['StartPrice'], dict) and '#text' in item['StartPrice']:
                    price = float(item['StartPrice']['#text'])
                else:
                    price = float(item['StartPrice'])
            elif 'BuyItNowPrice' in item:
                if isinstance(item['BuyItNowPrice'], dict) and '#text' in item['BuyItNowPrice']:
                    price = float(item['BuyItNowPrice']['#text'])
                else:
                    price = float(item['BuyItNowPrice'])
            
            # Extract picture URLs
            picture_urls = []
            gallery_url = None
            picture_details = item.get('PictureDetails', {})
            if picture_details:
                gallery_url = picture_details.get('GalleryURL')
                picture_url_list = picture_details.get('PictureURL', [])
                if isinstance(picture_url_list, str):
                    picture_urls = [picture_url_list]
                elif isinstance(picture_url_list, list):
                    picture_urls = picture_url_list
            
            # Extract listing details
            listing_details = item.get('ListingDetails', {})
            start_time = listing_details.get('StartTime')
            end_time = listing_details.get('EndTime')
            
            # Extract listing status
            selling_status = item.get('SellingStatus', {})
            listing_status = selling_status.get('ListingStatus', 'Active')
            # Normalize to lowercase
            listing_status = listing_status.lower() if listing_status else 'active'
            
            # Extract primary category info
            primary_category = item.get('PrimaryCategory', {})
            category_id = primary_category.get('CategoryID', '')
            category_name = primary_category.get('CategoryName', '')
            
            # Ensure consistent format for category name
            if category_name and 'Musical Instruments & Gear' in category_name:
                category_name = category_name.replace('Musical Instruments & Gear', 'Musical Instruments & DJ Equipment')
            
            # Extract condition display name
            condition_display_name = None
            if 'ConditionDisplayName' in item:
                condition_display_name = item.get('ConditionDisplayName')
            elif 'Condition' in item and isinstance(item['Condition'], dict):
                condition_display_name = item['Condition'].get('DisplayName')
            else:
                # Fallback to mapping from condition ID if not provided by API
                condition_id = item.get('ConditionID', '')
                if condition_id:
                    condition_display_map = {
                        "1000": "New",
                        "1500": "New other (see details)",
                        "2500": "Refurbished",
                        "3000": "Used",
                        "7000": "For parts or not working"
                    }
                    condition_display_name = condition_display_map.get(condition_id, "Used")
                
            listing_data = {
                'ebay_item_id': item.get('ItemID'),
                'title': item.get('Title', ''),
                'price': price,
                'category_id': category_id,
                'category_name': category_name,
                'condition_id': item.get('ConditionID', ''),
                'condition_display_name': condition_display_name,
                'listing_type': item.get('ListingType', 'FixedPriceItem'),
                'listing_duration': item.get('ListingDuration', 'GTC'),
                'listing_status': listing_status,
                'quantity': int(item.get('Quantity', 1)),
                'seller_profiles': item.get('SellerProfiles', {}),
                'sku': item.get('SKU', ''),
                'custom_sku': item.get('CustomLabel', ''),  # Sometimes SKU is stored here
                'item_specifics': item.get('ItemSpecifics', {}),
                'picture_urls': picture_urls,
                'gallery_url': gallery_url,
                'start_time': start_time,
                'end_time': end_time,
                'listing_details': listing_details,
                'view_item_url': item.get('ViewItemURL')  # Also capture the listing URL
            }
            
            logger.debug(f"Extracted listing data: {listing_data}")
            return listing_data
        else:
            logger.error(f"No 'Item' in response for {item_id}. Response: {response}")
            return None
    except Exception as e:
        logger.error(f"Error fetching item {item_id} from eBay: {e}", exc_info=True)
        return None

async def backfill_ebay_entries(items_to_process: list):
    """Backfill missing eBay database entries."""
    settings = Settings()
    trading_api = EbayTradingLegacyAPI(sandbox=settings.EBAY_SANDBOX_MODE)
    
    async with async_session() as db:
        for item_spec in items_to_process:
            if isinstance(item_spec, tuple):
                item_id, manual_sku = item_spec
            else:
                item_id, manual_sku = item_spec, None
            try:
                logger.info(f"\nProcessing eBay Item ID: {item_id}")
                
                # 1. Fetch listing info from eBay API
                listing_info = await get_listing_from_ebay(item_id, trading_api)
                if not listing_info:
                    logger.error(f"Could not fetch listing {item_id} from eBay API")
                    continue
                
                logger.info(f"Fetched listing: {listing_info['title']}")
                logger.info(f"  SKU: {listing_info['sku'] or listing_info['custom_sku'] or 'NOT FOUND'}")
                logger.info(f"  Price: £{listing_info['price']}")
                
                # 2. Find the product by SKU
                sku = manual_sku or listing_info['sku'] or listing_info['custom_sku']
                if not sku:
                    logger.error(f"No SKU found in eBay listing {item_id} and none provided manually")
                    logger.info("Try running with: python scripts/ebay/backfill_missing_ebay_entries.py {item_id}:{sku}")
                    continue
                    
                if manual_sku:
                    logger.info(f"Using manually provided SKU: {sku}")
                else:
                    logger.info(f"Using SKU from eBay listing: {sku}")
                
                result = await db.execute(
                    select(Product).where(Product.sku == sku)
                )
                product = result.scalar_one_or_none()
                
                if not product:
                    logger.error(f"Product with SKU {sku} not found in database!")
                    continue
                
                logger.info(f"Found product: {product.id} - {product.title}")
                
                # 3. Check if platform_common entry already exists
                pc_result = await db.execute(
                    select(PlatformCommon).where(
                        and_(
                            PlatformCommon.product_id == product.id,
                            PlatformCommon.platform_name == 'ebay',
                            PlatformCommon.external_id == item_id
                        )
                    )
                )
                existing_pc = pc_result.scalar_one_or_none()
                
                if existing_pc:
                    logger.warning(f"Platform common entry already exists for eBay ID {item_id}")
                    
                    # Check if ebay_listings entry exists
                    el_result = await db.execute(
                        select(EbayListing).where(
                            EbayListing.ebay_item_id == item_id
                        )
                    )
                    existing_el = el_result.scalar_one_or_none()
                    
                    if existing_el:
                        logger.info(f"eBay listing entry already exists. Skipping.")
                        continue
                    else:
                        logger.info(f"Creating missing ebay_listings entry...")
                        platform_common = existing_pc
                else:
                    # 4. Create platform_common entry
                    logger.info(f"Creating platform_common entry...")
                    platform_common = PlatformCommon(
                        product_id=product.id,
                        platform_name='ebay',
                        external_id=item_id,
                        status=ListingStatus.ACTIVE,
                        sync_status=SyncStatus.SYNCED,
                        last_sync=datetime.now(timezone.utc).replace(tzinfo=None),
                        listing_url=f"https://www.ebay.co.uk/itm/{item_id}",
                        platform_specific_data={
                            'backfilled': True,
                            'backfill_date': datetime.now(timezone.utc).isoformat(),
                            'sandbox': settings.EBAY_SANDBOX_MODE
                        }
                    )
                    db.add(platform_common)
                    await db.flush()  # Get the ID
                    logger.info(f"Created platform_common entry with ID: {platform_common.id}")
                
                # 5. Create ebay_listings entry if it doesn't exist
                if not existing_pc or not existing_el:
                    logger.info(f"Creating ebay_listings entry...")
                    
                    # Extract shipping profile IDs if present
                    seller_profiles = listing_info.get('seller_profiles', {})
                    shipping_profile_id = seller_profiles.get('SellerShippingProfile', {}).get('ShippingProfileID')
                    payment_profile_id = seller_profiles.get('SellerPaymentProfile', {}).get('PaymentProfileID')
                    return_profile_id = seller_profiles.get('SellerReturnProfile', {}).get('ReturnProfileID')
                    
                    # Parse dates if they exist
                    start_time = None
                    end_time = None
                    if listing_info.get('start_time'):
                        try:
                            start_time = datetime.fromisoformat(listing_info['start_time'].replace('Z', '+00:00')).replace(tzinfo=None)
                        except:
                            logger.warning(f"Could not parse start_time: {listing_info.get('start_time')}")
                    if listing_info.get('end_time'):
                        try:
                            end_time = datetime.fromisoformat(listing_info['end_time'].replace('Z', '+00:00')).replace(tzinfo=None)
                        except:
                            logger.warning(f"Could not parse end_time: {listing_info.get('end_time')}")
                    
                    # Calculate end_time if not provided
                    if not end_time and listing_info.get('listing_duration') == 'GTC' and start_time:
                        end_time = (start_time + timedelta(days=30)).replace(tzinfo=None)
                    
                    # Use consistent format values to match reference listings
                    format_value = 'FIXEDPRICEITEM' if listing_info['listing_type'] == 'FixedPriceItem' else 'AUCTION'
                    
                    ebay_listing = EbayListing(
                        platform_id=platform_common.id,
                        ebay_item_id=item_id,
                        title=listing_info['title'][:255],  # Ensure it fits in database
                        price=listing_info['price'],
                        quantity=listing_info['quantity'],
                        quantity_available=listing_info['quantity'],
                        ebay_category_id=listing_info['category_id'],
                        ebay_category_name=listing_info.get('category_name'),
                        ebay_condition_id=listing_info['condition_id'],
                        condition_display_name=listing_info.get('condition_display_name'),
                        format=format_value,  # Use consistent uppercase format
                        listing_status=listing_info.get('listing_status', 'active'),  # Use actual status from API
                        listing_url=f"https://www.ebay.co.uk/itm/{item_id}",  # Add listing URL
                        shipping_policy_id=shipping_profile_id,
                        payment_policy_id=payment_profile_id,
                        return_policy_id=return_profile_id,
                        gallery_url=listing_info.get('gallery_url'),
                        picture_urls=listing_info.get('picture_urls', []),
                        start_time=start_time,
                        end_time=end_time,
                        # Store eBay item specifics
                        item_specifics=listing_info.get('item_specifics', {}),
                        # Store additional eBay data
                        listing_data={
                            'sandbox': settings.EBAY_SANDBOX_MODE,
                            'backfilled': True,
                            'backfill_date': datetime.now(timezone.utc).isoformat(),
                            'listing_type': listing_info['listing_type'],
                            'listing_duration': listing_info['listing_duration'],
                            'listing_details': listing_info.get('listing_details', {}),
                            'view_item_url': listing_info.get('view_item_url')
                        }
                    )
                    db.add(ebay_listing)
                    logger.info(f"Created ebay_listings entry")
                
                # 6. Commit the transaction
                await db.commit()
                logger.info(f"✅ Successfully backfilled eBay listing {item_id} for product {product.sku}")
                
            except Exception as e:
                logger.error(f"Failed to backfill eBay listing {item_id}: {e}", exc_info=True)
                await db.rollback()
        
        # Verify the backfill
        logger.info("\n=== Verification ===")
        for item_spec in items_to_process:
            if isinstance(item_spec, tuple):
                item_id, _ = item_spec
            else:
                item_id = item_spec
            result = await db.execute(
                select(EbayListing).where(
                    EbayListing.ebay_item_id == item_id
                )
            )
            el = result.scalar_one_or_none()
            if el:
                logger.info(f"✅ eBay listing {item_id} found in database")
            else:
                logger.error(f"❌ eBay listing {item_id} NOT found in database")

async def main():
    parser = argparse.ArgumentParser(description='Backfill missing eBay database entries')
    parser.add_argument('item_ids', nargs='+', help='eBay item IDs to backfill (format: item_id or item_id:sku)')
    args = parser.parse_args()
    
    # Parse item_ids which can be in format "item_id" or "item_id:sku"
    items_to_process = []
    for item_spec in args.item_ids:
        if ':' in item_spec:
            item_id, sku = item_spec.split(':', 1)
            items_to_process.append((item_id, sku))
        else:
            items_to_process.append((item_spec, None))
    
    await backfill_ebay_entries(items_to_process)

if __name__ == "__main__":
    asyncio.run(main())