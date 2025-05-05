# app/services/ebay/trading.py
import logging
import xmltodict
import httpx
import json
import asyncio
import requests
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from app.services.ebay.auth import EbayAuthManager
from app.core.exceptions import EbayAPIError

logger = logging.getLogger(__name__)

class EbayTradingAPI:
    def __init__(self, sandbox: bool = False, site_id: str = '3'):
        self.auth_manager = EbayAuthManager(sandbox=sandbox)
        self.sandbox = sandbox
        self.site_id = site_id  # Default to UK (3)
        self.marketplace_id = "EBAY_GB"  # Default for UK
        self.compatibility_level = '1155'

        if sandbox:
            self.endpoint = "https://api.sandbox.ebay.com/sell/inventory/v1"
        else:
            self.endpoint = "https://api.ebay.com/sell/inventory/v1"

    async def _get_auth_token(self) -> str:
        """Get OAuth token for API requests"""
        return await self.auth_manager.get_access_token()

    async def _make_request(self, call_name: str, xml_request: str, api_type: str = 'trading') -> Dict:
        """Make a request to eBay API asynchronously"""
        
        auth_token = await self._get_auth_token()
        
        headers = {
            'X-EBAY-API-CALL-NAME': call_name,
            'X-EBAY-API-SITEID': self.site_id,
            'X-EBAY-API-COMPATIBILITY-LEVEL': self.compatibility_level,
            'Content-Type': 'text/xml'
        }
        # Set the correct endpoint based on API type
        if api_type == 'trading':
            endpoint = 'https://api.ebay.com/ws/api.dll'
            headers["X-EBAY-API-IAF-TOKEN"] = auth_token
        elif api_type == 'shopping':
            endpoint = 'https://open.api.ebay.com/shopping'
            headers["X-EBAY-API-IAF-TOKEN"] = auth_token
        else:
            raise ValueError(f"Unsupported API type: {api_type}")

        try:
            # Use asyncio to run the request in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(endpoint, headers=headers, data=xml_request)
            )

            if response.status_code != 200:
                print(f"Error in API call {call_name}: {response.text}")
                return {}

            # Parse XML response to dict - also run in thread pool to avoid blocking
            response_text = response.text
            response_dict = await loop.run_in_executor(
                None,
                lambda: xmltodict.parse(response_text)
            )

            return response_dict
        except Exception as e:
            print(f"Error in API call {call_name}: {str(e)}")
            return {}

    async def get_active_listings(self, page_num: int = 1, items_per_page: int = 200, include_details: bool = False) -> Dict[str, Any]:
        """
        Get active eBay listings for a specific page

        Args:
            page_num: Page number (1-based)
            items_per_page: Items per page (max 200)
            include_details: Whether to include detailed item information

        Returns:
            Dict containing active listings data
        """

        auth_token = await self._get_auth_token()
        
        xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
        <GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
            <RequesterCredentials>
                <eBayAuthToken>{auth_token}</eBayAuthToken>
            </RequesterCredentials>
            <ActiveList>
                <Include>true</Include>
                <Pagination>
                    <EntriesPerPage>{items_per_page}</EntriesPerPage>
                    <PageNumber>{page_num}</PageNumber>
                </Pagination>
            </ActiveList>
            <DetailLevel>ReturnAll</DetailLevel>
        </GetMyeBaySellingRequest>"""

        try:
            response_dict = await self._make_request('GetMyeBaySelling', xml_request)

            if 'GetMyeBaySellingResponse' not in response_dict:
                logger.error("Invalid response from GetMyeBaySelling")
                return {}

            # Return the ActiveList section
            return response_dict.get('GetMyeBaySellingResponse', {}).get('ActiveList', {})
        except Exception as e:
            logger.error(f"Error getting active listings: {str(e)}")
            return {}

    async def get_item_details(self, item_id: str) -> Dict[str, Any]:
        """
        Get detailed information for a specific eBay item

        Args:
            item_id: The eBay item ID

        Returns:
            Dict: Detailed item information
        """

        auth_token = await self._get_auth_token()
        
        xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
        <GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
            <RequesterCredentials>
                <eBayAuthToken>{auth_token}</eBayAuthToken>
            </RequesterCredentials>
            <ItemID>{item_id}</ItemID>
            <DetailLevel>ReturnAll</DetailLevel>
            <IncludeItemSpecifics>true</IncludeItemSpecifics>
            <IncludeDescription>true</IncludeDescription>
        </GetItemRequest>"""
    
        try:
            response_dict = await self._make_request('GetItem', xml_request)
            
            if 'GetItemResponse' not in response_dict:
                logger.error(f"Invalid response from GetItem for item {item_id}")
                return {}
            
            return response_dict.get('GetItemResponse', {}).get('Item', {})
        except Exception as e:
            logger.error(f"Error getting item details for item {item_id}: {str(e)}")
            return {}

    async def get_all_active_listings(self, include_details: bool = False) -> List[Dict[str, Any]]:
        """
        Get all active eBay listings with pagination

        Args:
            include_details: Whether to include detailed item information

        Returns:
            List of all active listing items with optional details
        """
        # Get first page to determine total number of pages
        first_page = await self.get_active_listings(page_num=1)

        # Check if we have pagination data
        pagination_result = first_page.get('PaginationResult', {})
        if not pagination_result:
            logger.error("No pagination information in eBay response")
            return []

        total_pages = int(pagination_result.get('TotalNumberOfPages', '1'))
        total_entries = int(pagination_result.get('TotalNumberOfEntries', '0'))

        logger.info(f"Found {total_entries} eBay listings across {total_pages} pages")

        # Extract items from first page
        all_items = []
        items = first_page.get('ItemArray', {}).get('Item', [])

        # Handle case where there's only one item (not returned as a list)
        if items and not isinstance(items, list):
            items = [items]

        if items:
            all_items.extend(items)
            logger.info(f"Added {len(items)} items from page 1, total: {len(all_items)}")

        # Fetch remaining pages if there are more than one
        if total_pages > 1:
            # Create tasks for all pages except the first one
            tasks = []
            for page in range(2, total_pages + 1):
                task = asyncio.create_task(self.get_active_listings(page_num=page))
                tasks.append((page, task))

            # Wait for all tasks to complete
            for page, task in tasks:
                try:
                    result = await task
                    items = result.get('ItemArray', {}).get('Item', [])
                    if items:
                        # Handle case where there's only one item
                        if not isinstance(items, list):
                            items = [items]
                        all_items.extend(items)
                        logger.info(f"Added {len(items)} items from page {page}, total: {len(all_items)}")
                except Exception as e:
                    logger.error(f"Error fetching page {page}: {str(e)}")
 
        # If detailed information is requested, fetch it for all items concurrently in batches
        if include_details and all_items:
            enriched_items = []

            # Process in smaller batches to avoid overwhelming the API
            batch_size = 50  # Adjust this based on your API rate limits
            for i in range(0, len(all_items), batch_size):
                batch = all_items[i:i+batch_size]
                batch_tasks = []

                # Create tasks for each item in the batch
                for item in batch:
                    item_id = item.get('ItemID')
                    task = asyncio.create_task(self.get_item_details(item_id))
                    batch_tasks.append((item, item_id, task))
                # Fields to exclude from the details object to avoid duplication
                duplicate_fields = [
                    'Description',  # Already extracted to top level
                    'ItemID',       # Already available at top level
                    'Title',        # Already available at top level
                    'StartPrice',   # Similar to CurrentPrice in basic listing
                    'Quantity',     # Already available at top level
                    'QuantityAvailable', # Already available at top level
                    'SKU',          # Already available at top level
                    'PictureDetails', # If you're extracting PictureURLs to the top level
                    'PrimaryCategory', # If you're extracting PrimaryCategoryID/Name to top level
                    'SellingStatus', # Already available at top level
                    'ListingDuration', # Already extracted to top level
                    'ListingType', # Already extracted to top level
                    'ListingDetails', # If this contains mostly duplicate info
                    'BuyItNowPrice',
                    'ShippingDetails',
                    'SellerProfiles',
                    'Location',
                    'Country',
                    'ConditionID',
                    'ConditionDisplayName',
                    'ItemSpecifics',
                    'TimeLeft',      # Already available at top level
                ]

                # Wait for all tasks in this batch to complete
                for item, item_id, task in batch_tasks:
                    try:
                        details = await task

                        # Start with the basic listing info
                        enriched_item = item.copy()

                        # Add a details section with the complete GetItem response
                        # enriched_item['details'] = details

                        # Add some commonly used fields directly to the main object
                        enriched_item.update({
                            'PrimaryCategoryID': details.get('PrimaryCategory', {}).get('CategoryID'),
                            'PrimaryCategoryName': details.get('PrimaryCategory', {}).get('CategoryName'),
                            'Description': details.get('Description'),
                            'PictureURLs': details.get('PictureDetails', {}).get('PictureURL', []),
                            'PaymentMethods': details.get('PaymentMethods', []),
                            'Location': details.get('Location'),
                            'Country': details.get('Country'),
                            'ConditionID': details.get('ConditionID'),
                            'ConditionDisplayName': details.get('ConditionDisplayName'),
                            'ItemSpecifics': details.get('ItemSpecifics', {})
                        })

                        # Create a clean details object without duplicate fields
                        filtered_details = {k: v for k, v in details.items() if k not in duplicate_fields}

                        # Add the filtered details section
                        enriched_item['details'] = filtered_details

                        enriched_items.append(enriched_item)
                        batch_idx = i + batch_tasks.index((item, item_id, task))
                        print(batch_idx, item_id, enriched_item['PrimaryCategoryID'], enriched_item['PrimaryCategoryName'])

                    except Exception as e:
                        logger.error(f"Error getting details for item {item_id}: {str(e)}")

                # Small delay between batches to avoid rate limiting
                if i + batch_size < len(all_items):
                    await asyncio.sleep(0.5)

            return enriched_items
        else:
            # Return basic listing information without details
            return all_items

    async def get_selling_listings(self, page_num: int = 1, items_per_page: int = 200, include_active: bool = True,
                                  include_sold: bool = True,
                                  include_unsold: bool = True) -> Dict[str, Any]:
        """
        Get eBay selling listings (active, sold, unsold) for a specific page

        Args:
            page_num: Page number (1-based)
            items_per_page: Items per page (max 200)
            include_active: Whether to include active listings
            include_sold: Whether to include sold listings
            include_unsold: Whether to include unsold listings

        Returns:
            Dict containing listings data
        """

        auth_token = await self._get_auth_token()

        xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
        <GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
            <RequesterCredentials>
                <eBayAuthToken>{auth_token}</eBayAuthToken>
            </RequesterCredentials>
        """

        if include_active:
            xml_request += f"""
            <ActiveList>
                <Include>true</Include>
                <Pagination>
                    <EntriesPerPage>{items_per_page}</EntriesPerPage>
                    <PageNumber>{page_num}</PageNumber>
                </Pagination>
            </ActiveList>
            """

        if include_sold:
            xml_request += f"""
            <SoldList>
                <Include>true</Include>
                <Pagination>
                    <EntriesPerPage>{items_per_page}</EntriesPerPage>
                    <PageNumber>{page_num}</PageNumber>
                </Pagination>
                <DurationInDays>60</DurationInDays>  <!-- Look for transactions in the last 60 days -->
                <OrderStatusFilter>All</OrderStatusFilter>  <!-- Include all order statuses -->
            </SoldList>
            <CompletedList>  <!-- Also try the CompletedList -->
                <Include>true</Include>
                <Pagination>
                    <EntriesPerPage>{items_per_page}</EntriesPerPage>
                    <PageNumber>{page_num}</PageNumber>
                </Pagination>
                <DurationInDays>60</DurationInDays>
            </CompletedList>
            """

        if include_unsold:
            xml_request += f"""
            <UnsoldList>
                <Include>true</Include>
                <Pagination>
                    <EntriesPerPage>{items_per_page}</EntriesPerPage>
                    <PageNumber>{page_num}</PageNumber>
                </Pagination>
            </UnsoldList>
            """

        xml_request += """
            <DetailLevel>ReturnAll</DetailLevel>
        </GetMyeBaySellingRequest>"""

        try:
            response_dict = await self._make_request('GetMyeBaySelling', xml_request)

            # print(type(response_dict))
            
            # print('GetMyeBaySellingResponse' in response_dict)
            if 'GetMyeBaySellingResponse' not in response_dict:
                logger.error("Invalid response from GetMyeBaySelling")
                return {}

             
            # Log the full response structure for debugging (just keys)
            result = response_dict.get('GetMyeBaySellingResponse', {})
            logger.info(f"GetMyeBaySellingResponse keys: {list(result.keys())}")

            if result:
                return result

            if 'Errors' in result:
                print(result['Errors'])

            # If SoldList is present, log its structure
            if 'SoldList' in result:
                sold_list = result.get('SoldList', {})
                logger.info(f"SoldList keys: {list(sold_list.keys())}")

                # Check if we have OrderTransactionArray instead of ItemArray
                if 'OrderTransactionArray' in sold_list:
                    logger.info("Found OrderTransactionArray in SoldList")
                    # Convert OrderTransactionArray to a format similar to ItemArray
                    order_transactions = sold_list.get('OrderTransactionArray', {}).get('OrderTransaction', [])
                    if order_transactions and not isinstance(order_transactions, list):
                        order_transactions = [order_transactions]

                    item_array = []
                    for transaction in order_transactions:
                        # Extract the item from the transaction and add it to our array
                        if 'Item' in transaction:
                            item = transaction['Item']
                            # Add transaction data to the item
                            item['Transaction'] = {k: v for k, v in transaction.items() if k != 'Item'}
                            item_array.append(item)

                    # Replace the SoldList structure with one that matches ActiveList
                    result['SoldList']['ItemArray'] = {'Item': item_array}

            return result
        except Exception as e:
            logger.error(f"Error getting selling listings: {str(e)}")
            return {}

    async def get_all_selling_listings(self, include_active: bool = True,
                                      include_sold: bool = True,
                                      include_unsold: bool = True,
                                      include_details: bool = True) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get all eBay selling listings with pagination and optional detailed information
        
        Args:
            include_active: Whether to include active listings
            include_sold: Whether to include sold listings
            include_unsold: Whether to include unsold listings
            include_details: Whether to include detailed item information
            
        Returns:
            Dict with keys 'active', 'sold', 'unsold' containing lists of items
        """
        result = {
            'active': [],
            'sold': [],
            'unsold': []
        }
        
        # Get first page to determine total pages for each list type
        first_page = await self.get_selling_listings(
            page_num=1, 
            include_active=include_active,
            include_sold=include_sold,
            include_unsold=include_unsold
        )
        
        # Process active listings if requested
        if include_active and 'ActiveList' in first_page:
            active_list = first_page.get('ActiveList', {})
            result['active'] = await self._process_listing_pages(active_list, 'ActiveList', include_details)
            
        # Process sold listings if requested
        if include_sold and 'SoldList' in first_page:
            sold_list = first_page.get('SoldList', {})
            # Also include details for sold listings
            result['sold'] = await self._process_listing_pages(sold_list, 'SoldList', include_details)
            
        # Process unsold listings if requested
        if include_unsold and 'UnsoldList' in first_page:
            unsold_list = first_page.get('UnsoldList', {})
            # Also include details for unsold listings
            result['unsold'] = await self._process_listing_pages(unsold_list, 'UnsoldList', include_details)
        
        return result

    async def _process_listing_pages(self, list_data: Dict[str, Any], list_type: str, include_details: bool = False, test_mode: bool = False) -> List[Dict[str, Any]]:
        """
        Process listing pages for a specific list type (active, sold, unsold)

        Args:
            list_data: Data for the first page of listings
            list_type: Type of listing ('ActiveList', 'SoldList', 'UnsoldList')
            include_details: Whether to include detailed item information
            test_mode: If True, limit to first page and few items for testing

        Returns:
            List of all items across all pages
        """
        # Check if we have pagination data
        pagination_result = list_data.get('PaginationResult', {})
        if not pagination_result:
            logger.error(f"No pagination information in eBay response for {list_type}")
            return []

        total_pages = int(pagination_result.get('TotalNumberOfPages', '1'))
        total_entries = int(pagination_result.get('TotalNumberOfEntries', '0'))

        # In test mode, we only process the first page
        if test_mode:
            logger.info(f"Test mode: Only processing page 1 of {total_pages} for {list_type}")
            total_pages = 1

        logger.info(f"Found {total_entries} eBay {list_type} listings across {total_pages} pages")

        all_items = []

        # Special handling for SoldList which uses OrderTransactionArray structure
        if list_type == 'SoldList' and 'OrderTransactionArray' in list_data:
            logger.info("Processing OrderTransactionArray for SoldList")
            order_transactions = list_data.get('OrderTransactionArray', {}).get('OrderTransaction', [])
            
            if order_transactions:
                if not isinstance(order_transactions, list):
                    order_transactions = [order_transactions]
                
                for transaction in order_transactions:
                    # The sold transaction structure has an extra layer
                    # The actual transaction is inside a 'Transaction' key
                    if 'Transaction' in transaction:
                        transaction_data = transaction['Transaction']
                        
                        # Now look for Item inside this transaction_data
                        if 'Item' in transaction_data:
                            # Extract the Item data
                            item = transaction_data['Item'].copy()
                            
                            # Ensure ItemID is available
                            if 'ItemID' in item:
                                # Add transaction details to the item
                                item['Transaction'] = {k: v for k, v in transaction_data.items() if k != 'Item'}
                                item['_listing_type'] = 'sold'
                                all_items.append(item)
                            else:
                                logger.warning(f"Skipping transaction with missing ItemID in Item data")
                        else:
                            logger.warning(f"Skipping transaction with no Item data in Transaction")
                    else:
                        logger.warning(f"Skipping transaction with no Transaction data: {list(transaction.keys())}")
                
                logger.info(f"Added {len(all_items)} items from {list_type} page 1")
            
            # Process remaining pages if any
            if total_pages > 1:
                for page in range(2, total_pages + 1):
                    logger.info(f"Fetching {list_type} page {page}/{total_pages}")
                    
                    result = await self.get_selling_listings(
                        page_num=page,
                        include_active=(list_type == 'ActiveList'),
                        include_sold=(list_type == 'SoldList'),
                        include_unsold=(list_type == 'UnsoldList')
                    )
                    
                    if list_type in result:
                        sold_list = result.get(list_type, {})
                        if 'OrderTransactionArray' in sold_list:
                            order_transactions = sold_list.get('OrderTransactionArray', {}).get('OrderTransaction', [])
                            
                            if order_transactions:
                                if not isinstance(order_transactions, list):
                                    order_transactions = [order_transactions]
                                
                                page_items = []
                                for transaction in order_transactions:
                                    if 'Transaction' in transaction:
                                        transaction_data = transaction['Transaction']
                                        
                                        if 'Item' in transaction_data:
                                            item = transaction_data['Item'].copy()
                                            if 'ItemID' in item:
                                                item['Transaction'] = {k: v for k, v in transaction_data.items() if k != 'Item'}
                                                item['_listing_type'] = 'sold'
                                                page_items.append(item)
                                
                                all_items.extend(page_items)
                                logger.info(f"Added {len(page_items)} items from {list_type} page {page}, total: {len(all_items)}")
        else:
            # Standard processing for non-SoldList (ActiveList or UnsoldList)
            items = list_data.get('ItemArray', {}).get('Item', [])

            # Handle case where there's only one item (not returned as a list)
            if items and not isinstance(items, list):
                items = [items]

            if items:
                # Add listing type to each item
                for item in items:
                    if list_type == 'ActiveList':
                        item['_listing_type'] = 'active'
                    elif list_type == 'UnsoldList':
                        item['_listing_type'] = 'unsold'

                all_items.extend(items)
                logger.info(f"Added {len(items)} items from {list_type} page 1, total: {len(all_items)}")
            
            # Fetch remaining pages if there are more than one
            if total_pages > 1:
                for page in range(2, total_pages + 1):
                    logger.info(f"Fetching {list_type} page {page}/{total_pages}")
                    
                    result = await self.get_selling_listings(
                        page_num=page,
                        include_active=(list_type == 'ActiveList'),
                        include_sold=(list_type == 'SoldList'),
                        include_unsold=(list_type == 'UnsoldList')
                    )
                    
                    if list_type in result:
                        next_list_data = result.get(list_type, {})
                        items = next_list_data.get('ItemArray', {}).get('Item', [])
                        
                        if items:
                            if not isinstance(items, list):
                                items = [items]
                            
                            # Add listing type to each item
                            for item in items:
                                if list_type == 'ActiveList':
                                    item['_listing_type'] = 'active'
                                elif list_type == 'UnsoldList':
                                    item['_listing_type'] = 'unsold'
                            
                            all_items.extend(items)
                            logger.info(f"Added {len(items)} items from {list_type} page {page}, total: {len(all_items)}")
        
        # If detailed information is requested, fetch it for all items
        if include_details and all_items:
            enriched_items = []

            # Define duplicate fields to exclude from details section
            duplicate_fields = [
                'Description',  # Already extracted to top level
                'ItemID',       # Already available at top level
                'Title',        # Already available at top level
                'StartPrice',   # Similar to CurrentPrice in basic listing
                'Quantity',     # Already available at top level
                'QuantityAvailable', # Already available at top level
                'SKU',          # Already available at top level
                'PictureDetails', # If you're extracting PictureURLs to the top level
                'PrimaryCategory', # If you're extracting PrimaryCategoryID/Name to top level
                'SellingStatus', # Already available at top level
                'ListingDuration', # Already extracted to top level
                'ListingType', # Already extracted to top level
                'ListingDetails', # If this contains mostly duplicate info
                'BuyItNowPrice',
                'ShippingDetails',
                'SellerProfiles',
                'Location',
                'Country',
                'ConditionID',
                'ConditionDisplayName',
                'ItemSpecifics',
                'TimeLeft',      # Already available at top level
            ]
            
            # Process in smaller batches to avoid overwhelming the API
            batch_size = 120  # Adjust based on your API rate limits
            for i in range(0, len(all_items), batch_size):
                batch = all_items[i:i+batch_size]
                batch_tasks = []

                # Create tasks for each item in the batch
                for item in batch:
                    item_id = item.get('ItemID')
                    if item_id:
                        task = asyncio.create_task(self.get_item_details(item_id))
                        batch_tasks.append((item, item_id, task))
                
                # Wait for all tasks in this batch to complete
                for item, item_id, task in batch_tasks:
                    try:
                        details = await task
                        
                        # Start with the basic listing info
                        enriched_item = item.copy()
                        
                        # Add a details section with the complete GetItem response
                        # enriched_item['details'] = details
                        
                        # Add some commonly used fields directly to the main object
                        if details:
                            enriched_item.update({
                                'PrimaryCategoryID': details.get('PrimaryCategory', {}).get('CategoryID'),
                                'PrimaryCategoryName': details.get('PrimaryCategory', {}).get('CategoryName'),
                                'Description': details.get('Description'),
                                'PictureURLs': details.get('PictureDetails', {}).get('PictureURL', []),
                                'PaymentMethods': details.get('PaymentMethods', []),
                                'Location': details.get('Location'),
                                'Country': details.get('Country'),
                                'ConditionID': details.get('ConditionID'),
                                'ConditionDisplayName': details.get('ConditionDisplayName')
                            })
                            
                            # Add ItemSpecifics if available
                            if 'ItemSpecifics' in details:
                                enriched_item['ItemSpecifics'] = details.get('ItemSpecifics')
                            
                            # Create a clean details object without duplicate fields
                            filtered_details = {k: v for k, v in details.items() if k not in duplicate_fields}
                            
                            # Add the filtered details section
                            enriched_item['details'] = filtered_details
                        
                        enriched_items.append(enriched_item)
                        batch_idx = i + batch_tasks.index((item, item_id, task))
                        logger.info(f"Enriched item {batch_idx+1}/{len(all_items)}: {item_id}")
                        
                    except Exception as e:
                        logger.error(f"Error getting details for item {item_id}: {str(e)}")
                        # Still include the basic item
                        enriched_items.append(item)
                
                # Small delay between batches to avoid rate limiting
                if i + batch_size < len(all_items):
                    await asyncio.sleep(0.5)
            
            return enriched_items
        
        # Return all items without trying to process them in the database
        return all_items

    async def analyze_listing_structures(self) -> Dict[str, Any]:
        """
        Analyze and print the structure of different eBay listing types
        
        Returns:
            Dict containing structure analysis
        """
        # Get a sample of each type of listing
        listings = await self.get_all_selling_listings(
            include_active=True,
            include_sold=True,
            include_unsold=True,
            include_details=True  # Get details for active listings
        )
        
        analysis = {}
        
        # Helper function to extract field structure
        def extract_structure(data, prefix=''):
            if isinstance(data, dict):
                result = {}
                for key, value in data.items():
                    path = f"{prefix}.{key}" if prefix else key
                    if isinstance(value, (dict, list)):
                        result[key] = extract_structure(value, path)
                    else:
                        result[key] = type(value).__name__
                return result
            elif isinstance(data, list) and data:
                # Take the first item as a sample
                sample = data[0]
                if isinstance(sample, (dict, list)):
                    return [extract_structure(sample, f"{prefix}[0]")]
                else:
                    return [type(sample).__name__]
            else:
                return type(data).__name__
        
        # Analyze each listing type
        # for listing_type in ['active', 'sold', 'unsold']:
        for listing_type in ['sold', 'unsold']:
            if listings[listing_type]:
                # Get a sample listing
                sample = listings[listing_type][0]
                
                # Extract and store structure
                analysis[listing_type] = {
                    'field_count': len(sample) if isinstance(sample, dict) else 0,
                    'structure': extract_structure(sample)
                }
                
                # Print structure for inspection
                print(f"\n=== {listing_type.upper()} LISTING STRUCTURE ===")
                print(f"Total fields: {analysis[listing_type]['field_count']}")
                print("Fields:")
                
                def print_structure(structure, level=0):
                    if isinstance(structure, dict):
                        for key, value in structure.items():
                            if isinstance(value, (dict, list)):
                                print("  " * level + f"{key}:")
                                print_structure(value, level + 1)
                            else:
                                print("  " * level + f"{key}: {value}")
                    elif isinstance(structure, list) and structure:
                        print("  " * level + f"[{type(structure[0]).__name__}]")
                        if isinstance(structure[0], (dict, list)):
                            print_structure(structure[0], level + 1)
                
                print_structure(analysis[listing_type]['structure'])
                
                # Print a JSON sample for the first item
                print(f"\nSample {listing_type.upper()} listing (first item):")
                print(json.dumps(sample, indent=2, default=str)[:5000] + "...(truncated)")
        
        return analysis

    async def save_listing_structures(self, output_file: str = "ebay_listing_structures.txt") -> None:
        """
        Analyze eBay listing structures and save to a text file
        
        Args:
            output_file: Path to the output file
        """
        import json
        import os
        
        # Get a sample of each type of listing
        listings = await self.get_all_selling_listings(
            include_active=True,
            include_sold=True,
            include_unsold=True,
            include_details=True  # Get details for active listings
        )
        
        # Open the output file
        with open(output_file, 'w') as f:
            f.write("=== EBAY LISTING STRUCTURES ANALYSIS ===\n\n")
            f.write(f"Analysis timestamp: {datetime.now(timezone.utc)().isoformat()}\n\n")
            
            # Write summary
            f.write("=== SUMMARY ===\n")
            f.write(f"Total active listings: {len(listings['active'])}\n")
            f.write(f"Total sold listings: {len(listings['sold'])}\n")
            f.write(f"Total unsold listings: {len(listings['unsold'])}\n\n")
            
            # Helper function to extract field structure
            def extract_structure(data, prefix=''):
                if isinstance(data, dict):
                    result = {}
                    for key, value in data.items():
                        path = f"{prefix}.{key}" if prefix else key
                        if isinstance(value, (dict, list)):
                            result[key] = extract_structure(value, path)
                        else:
                            result[key] = type(value).__name__
                    return result
                elif isinstance(data, list) and data:
                    # Take the first item as a sample
                    sample = data[0]
                    if isinstance(sample, (dict, list)):
                        return [extract_structure(sample, f"{prefix}[0]")]
                    else:
                        return [type(sample).__name__]
                else:
                    return type(data).__name__
            
            # Helper function to print structure to file
            def write_structure(f, structure, level=0):
                if isinstance(structure, dict):
                    for key, value in structure.items():
                        if isinstance(value, (dict, list)):
                            f.write("  " * level + f"{key}:\n")
                            write_structure(f, value, level + 1)
                        else:
                            f.write("  " * level + f"{key}: {value}\n")
                elif isinstance(structure, list) and structure:
                    f.write("  " * level + f"[{type(structure[0]).__name__}]\n")
                    if isinstance(structure[0], (dict, list)):
                        write_structure(f, structure[0], level + 1)
            
            # Analyze each listing type
            for listing_type in ['active', 'sold', 'unsold']:
                if listings[listing_type]:
                    f.write(f"\n\n=== {listing_type.upper()} LISTING STRUCTURE ===\n")
                    
                    # Get a sample listing
                    sample = listings[listing_type][0]
                    
                    # Write total field count
                    f.write(f"Total fields: {len(sample) if isinstance(sample, dict) else 0}\n")
                    f.write("Fields:\n")
                    
                    # Write field structure
                    structure = extract_structure(sample)
                    write_structure(f, structure)
                    
                    # Write a sample listing
                    f.write(f"\nSample {listing_type.upper()} listing (first item):\n")
                    formatted_json = json.dumps(sample, indent=2, default=str)
                    f.write(formatted_json)
                    
                    # If this is the active listing with details, also analyze the details structure separately
                    if listing_type == 'active' and 'details' in sample:
                        f.write("\n\n=== ACTIVE LISTING DETAILS ONLY ===\n")
                        details = sample['details']
                        f.write(f"Total detail fields: {len(details) if isinstance(details, dict) else 0}\n")
                        f.write("Detail fields:\n")
                        details_structure = extract_structure(details)
                        write_structure(f, details_structure)

        print(f"Listing structures saved to {os.path.abspath(output_file)}")

    async def execute_call(self, call_name: str, xml_request: str) -> Dict:
            """
            Execute a Trading API call
            
            Args:
                call_name: The API call name
                xml_request: The XML request body
                
            Returns:
                Dict: Response converted from XML to dict
            """
            auth_token = await self._get_auth_token()
            
            headers = {
                'X-EBAY-API-CALL-NAME': call_name,
                'X-EBAY-API-SITEID': self.site_id,
                'X-EBAY-API-COMPATIBILITY-LEVEL': self.compatibility_level,
                'X-EBAY-API-IAF-TOKEN': auth_token,
                'Content-Type': 'text/xml'
            }
            
            # This is the Trading API endpoint - NOT the Inventory API endpoint
            endpoint = 'https://api.ebay.com/ws/api.dll'
            
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        endpoint,
                        headers=headers,
                        content=xml_request
                    )
                    
                    if response.status_code != 200:
                        logger.error(f"eBay Trading API error: {response.text}")
                        raise EbayAPIError(f"Trading API call {call_name} failed: {response.text}")
                    
                    # Convert XML to dict
                    return xmltodict.parse(response.text)
                    
            except httpx.RequestError as e:
                logger.error(f"Network error in Trading API call: {str(e)}")
                raise EbayAPIError(f"Network error in Trading API call: {str(e)}")

    async def get_user_info(self) -> Dict[str, Any]:
        """
        Get information about the authenticated user
        
        Returns:
            Dict: User information
        """
        xml_request = """<?xml version="1.0" encoding="utf-8"?>
        <GetUserRequest xmlns="urn:ebay:apis:eBLBaseComponents">
            <DetailLevel>ReturnAll</DetailLevel>
        </GetUserRequest>"""
        
        try:
            response_dict = await self.execute_call('GetUser', xml_request)
            
            if 'GetUserResponse' not in response_dict:
                return {
                    'success': False,
                    'message': "Invalid response from eBay GetUser API"
                }
            
            return {
                'success': True,
                'user_data': response_dict.get('GetUserResponse', {}).get('User', {})
            }
        except Exception as e:
            logger.error(f"Error getting user info: {str(e)}")
            return {
                'success': False,
                'message': f"Error getting user info: {str(e)}"
            }

class EbayTradingAPIOld:
    """
    Client for eBay's Trading API (XML-based)
    Used for operations not yet available in the REST APIs
    """
    
    def __init__(self, sandbox: bool = False, site_id: str = '3'):
        """
        Initialize eBay Trading API client
        
        Args:
            sandbox: Whether to use sandbox environment
            site_id: eBay site ID (3 = UK)
        """
        self.sandbox = sandbox
        self.site_id = site_id
        self.compatibility_level = '1155'
        
        # Set endpoint based on environment
        if sandbox:
            self.endpoint = 'https://api.sandbox.ebay.com/ws/api.dll'
        else:
            self.endpoint = 'https://api.ebay.com/ws/api.dll'
        
        self.auth_manager = EbayAuthManager(sandbox=sandbox)
    
    async def _get_auth_token(self) -> str:
        """Get OAuth token for API requests"""
        return await self.auth_manager.get_access_token()
    
    async def get_all_active_listings(self) -> List[Dict[str, Any]]:
        """
        Get all active eBay listings with pagination
        
        Returns:
            List of all active listing items
        """
        # Get first page to determine total number of pages
        first_page = await self.get_active_listings(page_num=1)
        
        # Check if we have pagination data
        pagination_result = first_page.get('PaginationResult', {})
        if not pagination_result:
            logger.error("No pagination information in eBay response")
            return []
        
        total_pages = int(pagination_result.get('TotalNumberOfPages', '1'))
        total_entries = int(pagination_result.get('TotalNumberOfEntries', '0'))
        
        logger.info(f"Found {total_entries} eBay listings across {total_pages} pages")
        
        # Extract items from first page
        all_items = []
        items = first_page.get('ItemArray', {}).get('Item', [])
        
        # Handle case where there's only one item (not returned as a list)
        if items and not isinstance(items, list):
            items = [items]
        
        if items:
            all_items.extend(items)
        
        # Fetch remaining pages if there are more than one
        if total_pages > 1:
            for page in range(2, total_pages + 1):
                logger.info(f"Fetching eBay listings page {page} of {total_pages}")
                result = await self.get_active_listings(page_num=page)
                
                items = result.get('ItemArray', {}).get('Item', [])
                if items:
                    # Handle case where there's only one item
                    if not isinstance(items, list):
                        items = [items]
                    all_items.extend(items)
        
        return all_items

    async def get_active_listings(self, page_num: int = 1, items_per_page: int = 200) -> Dict[str, Any]:
        """
        Get active eBay listings for a specific page
        
        Args:
            page_num: Page number (1-based)
            items_per_page: Items per page (max 200)
            
        Returns:
            Dict containing active listings data
        """
        auth_token = await self._get_auth_token()
        
        xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
        <GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
            <RequesterCredentials>
                <eBayAuthToken>{auth_token}</eBayAuthToken>
            </RequesterCredentials>
            <ActiveList>
                <Include>true</Include>
                <Pagination>
                    <EntriesPerPage>{items_per_page}</EntriesPerPage>
                    <PageNumber>{page_num}</PageNumber>
                </Pagination>
            </ActiveList>
            <DetailLevel>ReturnAll</DetailLevel>
        </GetMyeBaySellingRequest>"""

        try:
            response_dict = await self.execute_call('GetMyeBaySelling', xml_request)
            
            if 'GetMyeBaySellingResponse' not in response_dict:
                logger.error("Invalid response from GetMyeBaySelling")
                return {}
            
            return response_dict.get('GetMyeBaySellingResponse', {}).get('ActiveList', {})
        except Exception as e:
            logger.error(f"Error getting active listings: {str(e)}")
            return {}