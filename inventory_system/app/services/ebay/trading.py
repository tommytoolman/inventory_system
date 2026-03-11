# app/services/ebay/trading.py
import os
import base64
import logging
import xmltodict
import httpx
import json
import asyncio
import requests
import warnings
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from xml.sax.saxutils import escape as xml_escape

from app.services.ebay.auth import EbayAuthManager
from app.core.exceptions import EbayAPIError

logger = logging.getLogger(__name__)

    
class EbayInventoryAPI:
    """Class for eBay Inventory API (REST) operations"""
    
    def __init__(self, sandbox: bool = False):
        self.auth_manager = EbayAuthManager(sandbox=sandbox)
        self.sandbox = sandbox
        self.marketplace_id = "EBAY_GB"  # Default for UK
        
        if sandbox:
            self.endpoint = "https://api.sandbox.ebay.com/sell/inventory/v1"
        else:
            self.endpoint = "https://api.ebay.com/sell/inventory/v1"
    
    async def _get_auth_token(self) -> str:
        """Get OAuth token for API requests"""
        return await self.auth_manager.get_access_token()
        
    async def _make_request(self, method: str, path: str, data: Dict = None, params: Dict = None) -> Dict:
        """Make a request to eBay Inventory API"""
        url = f"{self.endpoint}/{path}"
        auth_token = await self._get_auth_token()
        
        headers = {
            'Authorization': f'Bearer {auth_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        if self.marketplace_id:
            headers['X-EBAY-C-MARKETPLACE-ID'] = self.marketplace_id
            
        try:
            async with httpx.AsyncClient() as client:
                if method.upper() == 'GET':
                    response = await client.get(url, headers=headers, params=params)
                elif method.upper() == 'POST':
                    response = await client.post(url, headers=headers, json=data)
                elif method.upper() == 'PUT':
                    response = await client.put(url, headers=headers, json=data)
                elif method.upper() == 'DELETE':
                    response = await client.delete(url, headers=headers)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                    
            if response.status_code not in (200, 201, 204):
                logger.error(f"Error in API call {method} {path}: {response.text}")
                return {}
                
            if response.status_code == 204:  # No content
                return {}
                
            return response.json()
            
        except Exception as e:
            logger.error(f"Error in API call {method} {path}: {str(e)}")
            raise EbayAPIError(f"Inventory API error: {str(e)}")
            
    async def get_inventory_items(self, limit=100, offset=0) -> Dict:
        """Get inventory items"""
        params = {
            'limit': limit,
            'offset': offset
        }
        return await self._make_request('GET', 'inventory_item', params=params)
    

class EbayTradingLegacyAPI:
    """Class for eBay Trading API (XML-based) operations"""
    
    def __init__(self, sandbox: bool = False, site_id: str = '3'):
        # print(f"DEBUG: EbayTradingLegacyAPI.__init__ - Initializing. Sandbox: {sandbox}, SiteID: {site_id}")
        self.auth_manager = EbayAuthManager(sandbox=sandbox) # This will have its own init prints
        self.sandbox = sandbox
        self.site_id = site_id  # Default to UK (3)
        self.compatibility_level = '1155' # From your original, ensure it's current
        
        if sandbox:
            self.endpoint = "https://api.sandbox.ebay.com/ws/api.dll"
        else:
            self.endpoint = "https://api.ebay.com/ws/api.dll"
        # print(f"DEBUG: EbayTradingLegacyAPI.__init__ - Endpoint set to: {self.endpoint}")
            
    async def _get_auth_token(self) -> str:
        """Get OAuth token for API requests"""
        # print(f"DEBUG: EbayTradingLegacyAPI._get_auth_token - Entered.") # Your print "*** ENTERED _get_auth_token() METHOD ***" is also good
        token = await self.auth_manager.get_access_token() # This will have many prints from auth.py
        # print(f"DEBUG: EbayTradingLegacyAPI._get_auth_token - Token received from auth_manager (masked): {'********' + token[-5:] if token and len(token) > 5 else 'None or too short'}")
        if not token:
            # print("DEBUG: EbayTradingLegacyAPI._get_auth_token - ERROR: No token returned from auth_manager.")
            raise EbayAPIError("Failed to retrieve auth token for Trading API call.")
        return token
        
    async def _make_request(self, call_name: str, xml_request: str, attempt: int = 1) -> Dict: # Added attempt parameter for clarity
        """Make a request to eBay Trading API"""
        max_attempts = 3 # Define max retry attempts for network issues
        # print(f"DEBUG: EbayTradingLegacyAPI._make_request - Entered. CallName: {call_name}, Attempt: {attempt}")
        
        try:
            auth_token = await self._get_auth_token() # This calls the instrumented get_access_token
            # print(f"DEBUG: EbayTradingLegacyAPI._make_request - Auth token obtained for {call_name} (masked): {'********' + auth_token[-5:] if auth_token and len(auth_token) > 5 else 'None'}")
            
            headers = {
                'X-EBAY-API-CALL-NAME': call_name,
                'X-EBAY-API-COMPATIBILITY-LEVEL': self.compatibility_level,
                'X-EBAY-API-SITEID': self.site_id,
                # 'X-EBAY-API-APP-NAME': self.settings.EBAY_APP_ID, # Your original had APP-NAME, DEV-ID, CERT-ID
                # 'X-EBAY-API-DEV-NAME': self.settings.EBAY_DEV_ID, # These are for traditional API Access Rules (non-OAuth)
                # 'X-EBAY-API-CERT-NAME': self.settings.EBAY_CERT_ID, # If using OAuth, X-EBAY-API-IAF-TOKEN is primary
                'X-EBAY-API-IAF-TOKEN': auth_token, # This is for OAuth
                'Content-Type': 'text/xml'
            }
            masked_headers = {k: (v if k != 'X-EBAY-API-IAF-TOKEN' else '********' + v[-5:]) for k,v in headers.items()}
            # print(f"DEBUG: EbayTradingLegacyAPI._make_request - Request Headers for {call_name} (token masked): {masked_headers}")
            # print(f"DEBUG: EbayTradingLegacyAPI._make_request - XML Request for {call_name}: {xml_request[:500]}...") # Optionally log part of XML

            # Your print: print(f"*** ABOUT TO MAKE HTTP REQUEST TO: {self.endpoint} ***")
            # print(f"DEBUG: EbayTradingLegacyAPI._make_request - Posting to endpoint: {self.endpoint} for call: {call_name}")
            async with httpx.AsyncClient(timeout=60.0) as client: # Using a timeout
                response = await client.post(self.endpoint, content=xml_request, headers=headers)
            
            # Your print: print(f"*** HTTP RESPONSE STATUS: {response.status_code} ***")
            # print(f"DEBUG: EbayTradingLegacyAPI._make_request - Response status for {call_name}: {response.status_code}")
            # print(f"DEBUG: EbayTradingLegacyAPI._make_request - Response content for {call_name}: {response.text[:500]}...")

            if response.status_code != 200:
                # print(f"DEBUG: EbayTradingLegacyAPI._make_request - ERROR - API call {call_name} failed. Status: {response.status_code}, Body: {response.text[:500]}")
                # Consider if specific HTTP errors indicate a token issue that needs special handling or retry
                raise EbayAPIError(f"eBay Trading API call {call_name} failed with HTTP status {response.status_code}: {response.text[:500]}")

            try:
                if not response.text:
                    # print(f"DEBUG: EbayTradingLegacyAPI._make_request - ERROR - Empty response content for {call_name}. Status: {response.status_code}")
                    raise EbayAPIError(f"Empty response from eBay Trading API call {call_name} with status {response.status_code}")
                
                parsed_response = xmltodict.parse(response.text) # Or your preferred XML parser
                ack_status = parsed_response.get(call_name + 'Response', {}).get('Ack', 'NoAck')
                # print(f"DEBUG: EbayTradingLegacyAPI._make_request - Parsed XML for {call_name}. Ack: {ack_status}")
                
                # Check for eBay errors within a 200 OK response
                if ack_status != 'Success' and ack_status != 'Warning': # Warning is often a partial success
                    ebay_errors = parsed_response.get(call_name + 'Response', {}).get('Errors', [])
                    error_message = f"eBay API call {call_name} reported Ack: {ack_status}."
                    if ebay_errors:
                        first_error = ebay_errors[0] if isinstance(ebay_errors, list) else ebay_errors
                        error_message += f" ErrorCode: {first_error.get('ErrorCode')}, ShortMessage: {first_error.get('ShortMessage')}, LongMessage: {first_error.get('LongMessage')}"
                    # print(f"DEBUG: EbayTradingLegacyAPI._make_request - eBay Ack not Success for {call_name}. Message: {error_message}")
                    # Depending on the error code, you might want to raise EbayAPIError or handle specific token errors
                    # e.g., if ErrorCode indicates invalid token (931, 932, 17470 for OAuth token)
                    # For now, just returning the response for higher level to check Ack
                
                return parsed_response
            except Exception as e_parse:
                # print(f"DEBUG: EbayTradingLegacyAPI._make_request - EXCEPTION parsing XML response for {call_name}: {e_parse}")
                # print(f"DEBUG: EbayTradingLegacyAPI._make_request - Raw XML content that failed parsing for {call_name}: {response.text[:1000]}")
                raise EbayAPIError(f"Failed to parse XML response from {call_name}: {e_parse}")

        except httpx.TimeoutException as e_timeout:
            # print(f"DEBUG: EbayTradingLegacyAPI._make_request - httpx.TimeoutException for {call_name} on attempt {attempt}: {e_timeout}")
            if attempt < max_attempts:
                # print(f"DEBUG: EbayTradingLegacyAPI._make_request - Retrying {call_name} due to timeout, attempt {attempt + 1}/{max_attempts}")
                await asyncio.sleep(attempt * 2) # Exponential backoff for timeouts
                return await self._make_request(call_name, xml_request, attempt=attempt + 1)
            logger.error(f"Timeout making Trading API request {call_name} after {max_attempts} attempts: {e_timeout}", exc_info=True)
            raise EbayAPIError(f"Timeout on {call_name} after {max_attempts} attempts: {e_timeout}")
        except httpx.RequestError as e_req:
            # print(f"DEBUG: EbayTradingLegacyAPI._make_request - httpx.RequestError for {call_name} on attempt {attempt}: {e_req}")
            if attempt < max_attempts:
                # print(f"DEBUG: EbayTradingLegacyAPI._make_request - Retrying {call_name} due to RequestError, attempt {attempt + 1}/{max_attempts}")
                await asyncio.sleep(attempt)
                return await self._make_request(call_name, xml_request, attempt=attempt + 1)
            logger.error(f"Network error making Trading API request {call_name} after {max_attempts} attempts: {e_req}", exc_info=True)
            raise EbayAPIError(f"Network error on {call_name} after {max_attempts} attempts: {e_req}")
        except EbayAPIError as e_api: # Re-raise known API errors unless retryable
            # print(f"DEBUG: EbayTradingLegacyAPI._make_request - EbayAPIError for {call_name} on attempt {attempt}: {e_api}")
            # Check if this specific EbayAPIError is due to an invalid token that might have been fixed by a concurrent refresh
            # For now, just re-raising. Sophisticated retry for token errors would involve checking error codes.
            raise
        except Exception as e_generic:
            # print(f"DEBUG: EbayTradingLegacyAPI._make_request - Generic EXCEPTION for {call_name} on attempt {attempt}: {e_generic}")
            logger.error(f"Unexpected error in Trading API request {call_name}: {e_generic}", exc_info=True)
            raise EbayAPIError(f"Unexpected error on {call_name}: {e_generic}")

    @staticmethod
    def _format_datetime(value: datetime) -> str:
        if isinstance(value, str):
            return value
        if not isinstance(value, datetime):
            raise ValueError("Datetime value must be datetime or ISO string")
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    async def end_listing(self, item_id: str, reason_code: str = "NotAvailable") -> Dict:
        """End an active eBay listing"""
        xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
        <EndItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
            <RequesterCredentials>
                <eBayAuthToken>{await self._get_auth_token()}</eBayAuthToken>
            </RequesterCredentials>
            <ItemID>{item_id}</ItemID>
            <EndingReason>{reason_code}</EndingReason>
        </EndItemRequest>"""
        
        response = await self._make_request('EndItem', xml_request)
        return response

    async def revise_listing_price(self, item_id: str, new_price: float) -> Dict:
        """Revises the price of an existing FixedPriceItem listing."""
        xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
        <ReviseFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
            <RequesterCredentials>
                <eBayAuthToken>{await self._get_auth_token()}</eBayAuthToken>
            </RequesterCredentials>
            <Item>
                <ItemID>{item_id}</ItemID>
                <StartPrice>{new_price:.2f}</StartPrice>
            </Item>
        </ReviseFixedPriceItemRequest>"""
        
        response = await self._make_request('ReviseFixedPriceItem', xml_request)
        return response.get('ReviseFixedPriceItemResponse', {})

    async def revise_listing_quantity(self, item_id: str, quantity: int, sku: Optional[str] = None) -> Dict[str, Any]:
        """Update the quantity for a FixedPriceItem listing, preferring SKU-based revision when possible."""
        safe_quantity = max(int(quantity), 0)
        auth_token = await self._get_auth_token()

        if sku:
            escaped_sku = self._escape_xml_chars(sku)
        else:
            escaped_sku = None

        # Attempt to update via ReviseInventoryStatus when a SKU is available
        if escaped_sku:
            inventory_xml = f"""<?xml version="1.0" encoding="utf-8"?>
            <ReviseInventoryStatusRequest xmlns="urn:ebay:apis:eBLBaseComponents">
                <RequesterCredentials>
                    <eBayAuthToken>{auth_token}</eBayAuthToken>
                </RequesterCredentials>
                <InventoryStatus>
                    <ItemID>{item_id}</ItemID>
                    <SKU>{escaped_sku}</SKU>
                    <Quantity>{safe_quantity}</Quantity>
                </InventoryStatus>
            </ReviseInventoryStatusRequest>"""

            inventory_response = await self._make_request('ReviseInventoryStatus', inventory_xml)
            inventory_payload = inventory_response.get('ReviseInventoryStatusResponse', {})
            ack = inventory_payload.get('Ack')
            if ack in ('Success', 'Warning'):
                return {
                    'method': 'ReviseInventoryStatus',
                    'ack': ack,
                    'payload': inventory_payload,
                }

        # Fallback to ReviseFixedPriceItem with a direct quantity update
        quantity_xml = f"""<?xml version="1.0" encoding="utf-8"?>
        <ReviseFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
            <RequesterCredentials>
                <eBayAuthToken>{auth_token}</eBayAuthToken>
            </RequesterCredentials>
            <Item>
                <ItemID>{item_id}</ItemID>
                <Quantity>{safe_quantity}</Quantity>
            </Item>
        </ReviseFixedPriceItemRequest>"""

        quantity_response = await self._make_request('ReviseFixedPriceItem', quantity_xml)
        quantity_payload = quantity_response.get('ReviseFixedPriceItemResponse', {})
        return {
            'method': 'ReviseFixedPriceItem',
            'ack': quantity_payload.get('Ack'),
            'payload': quantity_payload,
        }

    async def revise_listing_images(self, item_id: str, images: List[str]) -> Dict:
        """Revises the images of an existing FixedPriceItem listing."""
        # Build PictureDetails XML
        picture_xml = ""
        for image_url in images:
            picture_xml += f"<PictureURL>{self._escape_xml_chars(image_url)}</PictureURL>\n            "
        
        xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
        <ReviseFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
            <RequesterCredentials>
                <eBayAuthToken>{await self._get_auth_token()}</eBayAuthToken>
            </RequesterCredentials>
            <Item>
                <ItemID>{item_id}</ItemID>
                <PictureDetails>
                    {picture_xml.strip()}
                </PictureDetails>
            </Item>
        </ReviseFixedPriceItemRequest>"""
        
        response = await self._make_request('ReviseFixedPriceItem', xml_request)
        return response.get('ReviseFixedPriceItemResponse', {})

    async def revise_listing_details(
        self,
        item_id: str,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        item_specifics: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        if not (title or description or item_specifics):
            return {"Ack": "NoChange"}

        specifics_xml = ""
        if item_specifics:
            name_value_blocks = []
            for name, value in item_specifics.items():
                if not value:
                    continue
                escaped_name = self._escape_xml_chars(name)
                escaped_value = self._escape_xml_chars(str(value))
                name_value_blocks.append(
                    f"<NameValueList><Name>{escaped_name}</Name><Value>{escaped_value}</Value></NameValueList>"
                )
            if name_value_blocks:
                specifics_xml = f"<ItemSpecifics>{''.join(name_value_blocks)}</ItemSpecifics>"

        title_xml = f"<Title>{self._escape_xml_chars(title)}</Title>" if title else ""
        description_xml = (
            f"<Description><![CDATA[{description}]]></Description>" if description else ""
        )

        xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
        <ReviseFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
            <RequesterCredentials>
                <eBayAuthToken>{await self._get_auth_token()}</eBayAuthToken>
            </RequesterCredentials>
            <Item>
                <ItemID>{item_id}</ItemID>
                {title_xml}
                {description_xml}
                {specifics_xml}
            </Item>
        </ReviseFixedPriceItemRequest>"""

        response = await self._make_request('ReviseFixedPriceItem', xml_request)
        return response.get('ReviseFixedPriceItemResponse', {})

    async def get_item_details(self, item_id: str) -> Dict[str, Any]:
        """Get detailed information for a specific eBay item"""
        xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
        <GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
            <RequesterCredentials>
                <eBayAuthToken>{await self._get_auth_token()}</eBayAuthToken>
            </RequesterCredentials>
            <ItemID>{item_id}</ItemID>
            <DetailLevel>ReturnAll</DetailLevel>
            <IncludeItemSpecifics>true</IncludeItemSpecifics>
            <IncludeDescription>true</IncludeDescription>
            <IncludeWatchCount>true</IncludeWatchCount>
        </GetItemRequest>"""

        response_dict = await self._make_request('GetItem', xml_request)
        
        if 'GetItemResponse' not in response_dict:
            return {}

        return response_dict.get('GetItemResponse', {}).get('Item', {})

    async def get_user_info(self) -> Dict:
        # print("DEBUG: EbayTradingLegacyAPI.get_user_info - Entered method.") # Your print "*** ENTERED get_user_info() METHOD ***"
        call_name = "GetUser"
        # Your original `execute_call` contained the XML structure.
        # The XML payload itself does not need the token if X-EBAY-API-IAF-TOKEN is used for OAuth.
        xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
        <GetUserRequest xmlns="urn:ebay:apis:eBLBaseComponents">
          <RequesterCredentials>
            {""}
          </RequesterCredentials>
          <DetailLevel>ReturnAll</DetailLevel>
        </GetUserRequest>"""
        # The <eBayAuthToken> within <RequesterCredentials> is for the older "Auth'n'Auth" tokens.
        # For OAuth User Access Tokens, the primary mechanism is the X-EBAY-API-IAF-TOKEN header.
        # If eBay *also* requires it in the payload (sometimes true for hybrid setups or older calls),
        # then you would need to fetch it via _get_auth_token() and insert it.
        # For now, assuming the header is sufficient for OAuth.
        # If your previous `execute_call` included a token in the XML, this might be a change.
        # Let's stick to your original structure more closely if it worked:
        # original_xml_request_from_execute_call = f"""<?xml version="1.0" encoding="utf-8"?>
        # <GetUserRequest xmlns="urn:ebay:apis:eBLBaseComponents">
        #   <RequesterCredentials>
        #     <eBayAuthToken>{await self._get_auth_token()}</eBayAuthToken>
        #   </RequesterCredentials>
        #   <DetailLevel>ReturnAll</DetailLevel>
        # </GetUserRequest>"""
        # Using a simpler payload assuming IAF token in header is primary for OAuth with Trading API
        xml_request_get_user = f"""<?xml version="1.0" encoding="utf-8"?>
        <GetUserRequest xmlns="urn:ebay:apis:eBLBaseComponents">
          <DetailLevel>ReturnAll</DetailLevel>
        </GetUserRequest>"""
        # print(f"DEBUG: EbayTradingLegacyAPI.get_user_info - XML for GetUser: {xml_request_get_user}")
        
        # Your original print: print(f"*** ABOUT TO CALL execute_call() ***")
        # `execute_call` functionality is now in `_make_request`
        response_dict = await self._make_request(call_name, xml_request_get_user) # This will have many prints
        
        get_user_response_data = response_dict.get(f"{call_name}Response", {})
        ack = get_user_response_data.get("Ack")
        # print(f"DEBUG: EbayTradingLegacyAPI.get_user_info - GetUserResponse Ack: {ack}")

        if ack == "Success" and "User" in get_user_response_data:
            user_data = get_user_response_data["User"]
            # print(f"DEBUG: EbayTradingLegacyAPI.get_user_info - GetUser call successful. UserID: {user_data.get('UserID')}")
            return {"success": True, "user_data": user_data, "raw_response": response_dict}
        else:
            errors = get_user_response_data.get("Errors", {})
            error_message = f"GetUser failed or User data not found. Ack: {ack}."
            if isinstance(errors, list) and errors:
                error_message += f" First Error: {errors[0].get('LongMessage', 'No LongMessage')}"
            elif isinstance(errors, dict) and errors: # If Errors is a dict (single error)
                error_message += f" Error: {errors.get('LongMessage', 'No LongMessage')}"
            # print(f"DEBUG: EbayTradingLegacyAPI.get_user_info - GetUser call failed. {error_message}")
            return {"success": False, "message": error_message, "raw_response": response_dict}

    async def get_item(self, item_id: str) -> Dict:
        # print(f"DEBUG: EbayTradingLegacyAPI.get_item - Entered. ItemID: {item_id}")
        call_name = "GetItem"
        xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
        <GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
          <ItemID>{item_id}</ItemID>
          <DetailLevel>ReturnAll</DetailLevel>
          <IncludeItemSpecifics>true</IncludeItemSpecifics>
        </GetItemRequest>"""
        # print(f"DEBUG: EbayTradingLegacyAPI.get_item - XML for {call_name}: {xml_request}")
        return await self._make_request(call_name, xml_request)

    async def get_my_ebay_selling(self, detail_level: str = "ReturnAll", page_number: int = 1, entries_per_page: int = 25, list_name: str = "ActiveList") -> Dict:
        # print(f"DEBUG: EbayTradingLegacyAPI.get_my_ebay_selling - Entered. ListName: {list_name}, Page: {page_number}, Entries: {entries_per_page}, DetailLevel: {detail_level}")
        call_name = "GetMyeBaySelling"
        
        # Constructing list part based on list_name
        list_xml_part = f"""
        <{list_name}>
          <Include>true</Include>
          <Pagination>
            <EntriesPerPage>{entries_per_page}</EntriesPerPage>
            <PageNumber>{page_number}</PageNumber>
          </Pagination>
        </{list_name}>"""

        xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
        <GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
          <DetailLevel>{detail_level}</DetailLevel>
          {list_xml_part}
        </GetMyeBaySellingRequest>"""
        # print(f"DEBUG: EbayTradingLegacyAPI.get_my_ebay_selling - XML for {call_name} ({list_name}): {xml_request}")
        return await self._make_request(call_name, xml_request) # This will have its own prints

    async def get_all_selling_listings(self, include_active=True, include_sold=True, include_unsold=True, include_details=False) -> Dict[str, List[Dict]]:
        # print(f"DEBUG: EbayTradingLegacyAPI.get_all_selling_listings - Entered. Active: {include_active}, Sold: {include_sold}, Unsold: {include_unsold}, Details: {include_details}")
        all_listings_data = {"active": [], "sold": [], "unsold": []}
        
        detail_level_val = "ReturnAll" if include_details else "ReturnSummary"
        entries_per_page_val = 100 # Max for sold is 100, active is 200. Using 100 for simplicity.

        list_types_to_fetch = []
        if include_active: list_types_to_fetch.append("ActiveList")
        if include_sold: list_types_to_fetch.append("SoldList")
        if include_unsold: list_types_to_fetch.append("UnsoldList")

        for list_type in list_types_to_fetch:
            current_page = 1
            total_pages = 1 # Start with 1, will be updated by response
            # print(f"DEBUG: EbayTradingLegacyAPI.get_all_selling_listings - Starting fetch for ListType: {list_type}")
            
            while current_page <= total_pages:
                # print(f"DEBUG: EbayTradingLegacyAPI.get_all_selling_listings - Fetching Page: {current_page}/{total_pages} for ListType: {list_type}")
                try:
                    response_dict = await self.get_my_ebay_selling(
                        detail_level=detail_level_val,
                        page_number=current_page,
                        entries_per_page=entries_per_page_val,
                        list_name=list_type
                    ) # This method now has its own debug prints

                    get_mye_bay_selling_response = response_dict.get("GetMyeBaySellingResponse", {})
                    ack = get_mye_bay_selling_response.get("Ack")
                    # print(f"DEBUG: EbayTradingLegacyAPI.get_all_selling_listings - Ack for {list_type} Page {current_page}: {ack}")

                    if ack == "Success" or ack == "Warning": # Warning might still have data
                        list_data_container = get_mye_bay_selling_response.get(list_type)
                        if list_data_container:
                            # Update total_pages from PaginationResult if available
                            pagination_result = list_data_container.get("PaginationResult")
                            if pagination_result and "TotalNumberOfPages" in pagination_result:
                                total_pages = int(pagination_result["TotalNumberOfPages"])
                                # print(f"DEBUG: EbayTradingLegacyAPI.get_all_selling_listings - Updated TotalPages for {list_type} to: {total_pages} based on response.")
                            else: # No more pages if PaginationResult or TotalNumberOfPages is missing
                                total_pages = current_page 

                            items_key = "ItemArray" if list_type != "SoldList" else "OrderTransactionArray"
                            item_or_transaction_key = "Item" if list_type != "SoldList" else "OrderTransaction"
                            
                            if items_key in list_data_container and list_data_container[items_key]:
                                raw_items = list_data_container[items_key].get(item_or_transaction_key, [])
                                items_to_add = raw_items if isinstance(raw_items, list) else [raw_items]
                                
                                if list_type == "ActiveList":
                                    all_listings_data["active"].extend(items_to_add)
                                elif list_type == "UnsoldList":
                                    all_listings_data["unsold"].extend(items_to_add)
                                elif list_type == "SoldList": # SoldList structure is OrderTransactionArray -> OrderTransaction -> Item
                                    for trans_item in items_to_add:
                                        if trans_item and "Item" in trans_item:
                                            all_listings_data["sold"].append(trans_item["Item"])
                                        elif trans_item and "Transaction" in trans_item and "Item" in trans_item["Transaction"]: # Another possible structure
                                             all_listings_data["sold"].append(trans_item["Transaction"]["Item"])
                                        elif trans_item: # If the item itself is the transaction data
                                            all_listings_data["sold"].append(trans_item)


                                # print(f"DEBUG: EbayTradingLegacyAPI.get_all_selling_listings - Fetched {len(items_to_add)} items for {list_type} Page {current_page}. Total so far for {list_type}: {len(all_listings_data[list_type.replace('List','').lower()])}")
                            else: # No items found for this list type on this page
                                # print(f"DEBUG: EbayTradingLegacyAPI.get_all_selling_listings - No '{items_key}' or empty for {list_type} Page {current_page}. Assuming end of pages for this list.")
                                total_pages = current_page # Stop pagination for this list type
                        else: # list_data_container (e.g. ActiveList) itself is missing
                            # print(f"DEBUG: EbayTradingLegacyAPI.get_all_selling_listings - List container '{list_type}' missing in response for Page {current_page}. Assuming end of pages.")
                            total_pages = current_page # Stop pagination

                    else: # Ack was not Success or Warning
                        ebay_errors = get_mye_bay_selling_response.get("Errors", {})
                        error_message = f"GetMyeBaySelling failed for {list_type} Page {current_page}. Ack: {ack}."
                        # ... (error message construction as in get_user_info) ...
                        # print(f"DEBUG: EbayTradingLegacyAPI.get_all_selling_listings - {error_message}")
                        # Break from while loop for this list_type on error
                        break 
                    
                    current_page += 1
                    if current_page > total_pages: # Safety break if total_pages wasn't updated correctly to a smaller number
                        print(f"EbayTradingLegacyAPI.get_all_selling_listings - Reached end of pagination for {list_type}. CurrentPage: {current_page}, TotalPages: {total_pages}")

                except EbayAPIError as e_api_paginate:
                    # print(f"DEBUG: EbayTradingLegacyAPI.get_all_selling_listings - EbayAPIError while paginating {list_type} on page {current_page}: {e_api_paginate}")
                    break # Stop paginating this list type on API error
                except Exception as e_paginate:
                    # print(f"DEBUG: EbayTradingLegacyAPI.get_all_selling_listings - Generic EXCEPTION while paginating {list_type} on page {current_page}: {e_paginate}")
                    break # Stop paginating this list type

        # print(f"DEBUG: EbayTradingLegacyAPI.get_all_selling_listings - Finished fetching all lists. Total active: {len(all_listings_data['active'])}, sold: {len(all_listings_data['sold'])}, unsold: {len(all_listings_data['unsold'])}")
        return all_listings_data

    async def get_orders(
        self,
        *,
        number_of_days: Optional[int] = 30,
        created_time_from: Optional[datetime] = None,
        created_time_to: Optional[datetime] = None,
        last_modified_from: Optional[datetime] = None,
        last_modified_to: Optional[datetime] = None,
        order_status: str = "All",
        order_role: str = "Seller",
        entries_per_page: int = 100,
        page_number: int = 1,
        detail_level: str = "ReturnAll",
    ) -> Dict[str, Any]:
        if entries_per_page <= 0:
            entries_per_page = 1
        entries_per_page = min(entries_per_page, 100)

        time_filters = ""
        if created_time_from and created_time_to:
            time_filters = (
                f"<CreateTimeFrom>{self._format_datetime(created_time_from)}</CreateTimeFrom>"
                f"<CreateTimeTo>{self._format_datetime(created_time_to)}</CreateTimeTo>"
            )
        elif last_modified_from and last_modified_to:
            time_filters = (
                f"<ModTimeFrom>{self._format_datetime(last_modified_from)}</ModTimeFrom>"
                f"<ModTimeTo>{self._format_datetime(last_modified_to)}</ModTimeTo>"
            )
        elif number_of_days:
            time_filters = f"<NumberOfDays>{int(number_of_days)}</NumberOfDays>"
        else:
            raise ValueError("GetOrders requires number_of_days or a time range")

        xml_request = f"""<?xml version=\"1.0\" encoding=\"utf-8\"?>
        <GetOrdersRequest xmlns=\"urn:ebay:apis:eBLBaseComponents\">
          <DetailLevel>{detail_level}</DetailLevel>
          <Pagination>
            <EntriesPerPage>{entries_per_page}</EntriesPerPage>
            <PageNumber>{page_number}</PageNumber>
          </Pagination>
          <OrderRole>{order_role}</OrderRole>
          <OrderStatus>{order_status}</OrderStatus>
          {time_filters}
        </GetOrdersRequest>"""

        response = await self._make_request("GetOrders", xml_request)
        payload = response.get("GetOrdersResponse") or {}
        order_array = payload.get("OrderArray") or {}
        orders = order_array.get("Order") or []
        if isinstance(orders, dict):
            orders = [orders]

        has_more = payload.get("HasMoreOrders", False)
        if isinstance(has_more, str):
            has_more = has_more.lower() == "true"

        return {
            "orders": orders or [],
            "raw": payload,
            "has_more": has_more,
            "pagination": payload.get("PaginationResult", {}),
            "ack": payload.get("Ack"),
        }

    async def get_total_active_listings_count(self) -> int:
        # print("DEBUG: EbayTradingLegacyAPI.get_total_active_listings_count - Entered.")
        # This method uses get_my_ebay_selling, which is now instrumented.
        # We need to parse its result here.
        try:
            response_dict = await self.get_my_ebay_selling(
                detail_level="ReturnSummary", 
                list_name="ActiveList",
                entries_per_page=1 # We only need pagination summary
            )
            get_mye_bay_selling_response = response_dict.get("GetMyeBaySellingResponse", {})
            ack = get_mye_bay_selling_response.get("Ack")

            if ack == "Success" or ack == "Warning":
                active_list_data = get_mye_bay_selling_response.get("ActiveList")
                if active_list_data and "PaginationResult" in active_list_data:
                    count = int(active_list_data["PaginationResult"].get("TotalNumberOfEntries", 0))
                    # print(f"DEBUG: EbayTradingLegacyAPI.get_total_active_listings_count - Count from PaginationResult: {count}")
                    return count
                else:
                    # print("DEBUG: EbayTradingLegacyAPI.get_total_active_listings_count - ActiveList or PaginationResult missing in successful response.")
                    return 0 # Or handle as an error
            else:
                error_msg = get_mye_bay_selling_response.get("Errors", {}).get("LongMessage", "Unknown error retrieving active count summary")
                # print(f"DEBUG: EbayTradingLegacyAPI.get_total_active_listings_count - Error getting count. Ack: {ack}, Message: {error_msg}")
                return 0
        except Exception as e:
            # print(f"DEBUG: EbayTradingLegacyAPI.get_total_active_listings_count - EXCEPTION: {e}")
            return 0

    async def add_fixed_price_item(self, item_data: Dict) -> Dict:
        """
        Add a fixed price item to eBay

        Args:
            item_data: Dictionary containing all item details

        Returns:
            Dict: Response data with new item ID
        """
        # Construct XML from item_data
        xml_parts = ["<?xml version=\"1.0\" encoding=\"utf-8\"?>"]
        xml_parts.append("<AddFixedPriceItemRequest xmlns=\"urn:ebay:apis:eBLBaseComponents\">")
        xml_parts.append(f"<RequesterCredentials><eBayAuthToken>{await self._get_auth_token()}</eBayAuthToken></RequesterCredentials>")
        
        # Add Item element and its children
        xml_parts.append("<Item>")
        
        # Required fields
        xml_parts.append(f"<Title>{self._escape_xml_chars(item_data.get('Title', ''))}</Title>")
        xml_parts.append(f"<Description><![CDATA[{item_data.get('Description', '')}]]></Description>")
        
        # Category
        xml_parts.append("<PrimaryCategory>")
        xml_parts.append(f"<CategoryID>{self._escape_xml_chars(item_data.get('CategoryID', ''))}</CategoryID>")
        xml_parts.append("</PrimaryCategory>")
        
        # Price and currency
        xml_parts.append(
            f"<StartPrice currencyID=\"{self._escape_xml_chars(item_data.get('CurrencyID', 'GBP'))}\">{self._escape_xml_chars(item_data.get('Price', '0.0'))}</StartPrice>"
        )
        
        # Add Currency element (required by eBay)
        # This is the fix: ensure Currency tag is always included
        currency = item_data.get('Currency', item_data.get('CurrencyID', 'GBP'))
        xml_parts.append(f"<Currency>{self._escape_xml_chars(currency)}</Currency>")
        
        # Quantity
        xml_parts.append(f"<Quantity>{self._escape_xml_chars(item_data.get('Quantity', '1'))}</Quantity>")
        
        # SKU (Stock Keeping Unit) - important for tracking
        if "SKU" in item_data:
            xml_parts.append(f"<SKU>{self._escape_xml_chars(item_data.get('SKU'))}</SKU>")
        
        # Listing details
        xml_parts.append(f"<ListingDuration>{self._escape_xml_chars(item_data.get('ListingDuration', 'GTC'))}</ListingDuration>")  # Good Till Cancelled
        xml_parts.append("<ListingType>FixedPriceItem</ListingType>")
        
        # Condition
        if "ConditionID" in item_data:
            xml_parts.append(f"<ConditionID>{self._escape_xml_chars(item_data.get('ConditionID'))}</ConditionID>")
        
        # Item specifics
        if "ItemSpecifics" in item_data and item_data["ItemSpecifics"]:
            xml_parts.append("<ItemSpecifics>")
            for name, value in item_data["ItemSpecifics"].items():
                xml_parts.append("<NameValueList>")
                xml_parts.append(f"<Name>{self._escape_xml_chars(name)}</Name>")
                if isinstance(value, list):
                    for v in value:
                        xml_parts.append(f"<Value>{self._escape_xml_chars(v)}</Value>")
                else:
                    xml_parts.append(f"<Value>{self._escape_xml_chars(value)}</Value>")
                xml_parts.append("</NameValueList>")
            xml_parts.append("</ItemSpecifics>")
        
        # Pictures
        if "PictureURLs" in item_data and item_data["PictureURLs"]:
            xml_parts.append("<PictureDetails>")
            for url in item_data["PictureURLs"]:
                xml_parts.append(f"<PictureURL>{self._escape_xml_chars(url)}</PictureURL>")
            xml_parts.append("</PictureDetails>")
        
        # In app/services/ebay/trading.py around line 500
        # DispatchTimeMax moved to later section to avoid duplication
        
        # Add SellerProfiles if using Business Policies
        if "SellerProfiles" in item_data:
            profiles = item_data["SellerProfiles"]
            xml_parts.append("<SellerProfiles>")
            
            if "SellerShippingProfile" in profiles:
                xml_parts.append("<SellerShippingProfile>")
                xml_parts.append(f"<ShippingProfileID>{self._escape_xml_chars(profiles['SellerShippingProfile']['ShippingProfileID'])}</ShippingProfileID>")
                xml_parts.append("</SellerShippingProfile>")
            
            if "SellerPaymentProfile" in profiles:
                xml_parts.append("<SellerPaymentProfile>")
                xml_parts.append(f"<PaymentProfileID>{self._escape_xml_chars(profiles['SellerPaymentProfile']['PaymentProfileID'])}</PaymentProfileID>")
                xml_parts.append("</SellerPaymentProfile>")
            
            if "SellerReturnProfile" in profiles:
                xml_parts.append("<SellerReturnProfile>")
                xml_parts.append(f"<ReturnProfileID>{self._escape_xml_chars(profiles['SellerReturnProfile']['ReturnProfileID'])}</ReturnProfileID>")
                xml_parts.append("</SellerReturnProfile>")
            
            xml_parts.append("</SellerProfiles>")
        
        # Shipping details - only add if NOT using Business Policies
        if "ShippingDetails" in item_data and item_data["ShippingDetails"] and "SellerProfiles" not in item_data:
            xml_parts.append("<ShippingDetails>")
            
            shipping_details = item_data["ShippingDetails"]
            
            # Add shipping type if specified
            if "ShippingType" in shipping_details:
                xml_parts.append(f"<ShippingType>{self._escape_xml_chars(shipping_details['ShippingType'])}</ShippingType>")
            else:
                xml_parts.append("<ShippingType>Flat</ShippingType>")
            
            # Add domestic shipping options
            if "ShippingServiceOptions" in shipping_details:
                services = shipping_details["ShippingServiceOptions"]
                # Handle both single object (legacy) and array (new) formats
                if not isinstance(services, list):
                    services = [services]
                for service in services:
                    xml_parts.append("<ShippingServiceOptions>")
                    xml_parts.append(f"<ShippingServicePriority>{self._escape_xml_chars(service.get('ShippingServicePriority', '1'))}</ShippingServicePriority>")
                    xml_parts.append(f"<ShippingService>{self._escape_xml_chars(service.get('ShippingService', 'UK_OtherCourier24'))}</ShippingService>")
                    xml_parts.append(f"<ShippingServiceCost currencyID=\"GBP\">{self._escape_xml_chars(service.get('ShippingServiceCost', '0.0'))}</ShippingServiceCost>")
                    if service.get('ShippingServiceAdditionalCost') is not None:
                        xml_parts.append(
                            f"<ShippingServiceAdditionalCost currencyID=\"GBP\">{self._escape_xml_chars(service.get('ShippingServiceAdditionalCost'))}</ShippingServiceAdditionalCost>"
                        )
                    if service.get('FreeShipping'):
                        xml_parts.append("<FreeShipping>true</FreeShipping>")
                    xml_parts.append("</ShippingServiceOptions>")

            # Add international shipping options
            if "InternationalShippingServiceOption" in shipping_details:
                intl_services = shipping_details["InternationalShippingServiceOption"]
                # Handle both single object (legacy) and array (new) formats
                if not isinstance(intl_services, list):
                    intl_services = [intl_services]
                for intl_service in intl_services:
                    xml_parts.append("<InternationalShippingServiceOption>")
                    xml_parts.append(f"<ShippingServicePriority>{self._escape_xml_chars(intl_service.get('ShippingServicePriority', '1'))}</ShippingServicePriority>")
                    xml_parts.append(f"<ShippingService>{self._escape_xml_chars(intl_service.get('ShippingService', 'UK_InternationalStandard'))}</ShippingService>")
                    xml_parts.append(f"<ShippingServiceCost currencyID=\"GBP\">{self._escape_xml_chars(intl_service.get('ShippingServiceCost', '0.0'))}</ShippingServiceCost>")
                    if intl_service.get('ShippingServiceAdditionalCost') is not None:
                        xml_parts.append(
                            f"<ShippingServiceAdditionalCost currencyID=\"GBP\">{self._escape_xml_chars(intl_service.get('ShippingServiceAdditionalCost'))}</ShippingServiceAdditionalCost>"
                        )
                    ship_to = intl_service.get('ShipToLocation', 'Worldwide')
                    if isinstance(ship_to, (list, tuple, set)):
                        for destination in ship_to:
                            xml_parts.append(f"<ShipToLocation>{self._escape_xml_chars(destination)}</ShipToLocation>")
                    else:
                        xml_parts.append(f"<ShipToLocation>{self._escape_xml_chars(ship_to)}</ShipToLocation>")
                    xml_parts.append("</InternationalShippingServiceOption>")
            
            xml_parts.append("</ShippingDetails>")
        
        # Payment methods - only add if NOT using Business Policies
        if "SellerProfiles" not in item_data:
            if "PaymentMethods" in item_data:
                payment_methods = item_data["PaymentMethods"]
                if isinstance(payment_methods, list):
                    for method in payment_methods:
                        xml_parts.append(f"<PaymentMethods>{self._escape_xml_chars(method)}</PaymentMethods>")
                else:
                    xml_parts.append(f"<PaymentMethods>{self._escape_xml_chars(payment_methods)}</PaymentMethods>")
            # Don't add PayPal as default - eBay manages payments now
        
        # PayPal email
        # paypal_email = item_data.get('PayPalEmailAddress', self._get_paypal_email())
        # xml_parts.append(f"<PayPalEmailAddress>{paypal_email}</PayPalEmailAddress>")
        
        # Return policy - only add if NOT using Business Policies
        if "ReturnPolicy" in item_data and "SellerProfiles" not in item_data:
            policy = item_data["ReturnPolicy"]
            xml_parts.append("<ReturnPolicy>")
            xml_parts.append(f"<ReturnsAcceptedOption>{self._escape_xml_chars(policy.get('ReturnsAccepted', 'ReturnsAccepted'))}</ReturnsAcceptedOption>")
            xml_parts.append(f"<ReturnsWithinOption>{self._escape_xml_chars(policy.get('ReturnsWithin', 'Days_30'))}</ReturnsWithinOption>")
            xml_parts.append(f"<ShippingCostPaidByOption>{self._escape_xml_chars(policy.get('ShippingCostPaidBy', 'Buyer'))}</ShippingCostPaidByOption>")
            xml_parts.append("</ReturnPolicy>")
        
        # Location and country
        xml_parts.append(f"<Location>{self._escape_xml_chars(item_data.get('Location', 'London, UK'))}</Location>")
        xml_parts.append(f"<Country>{self._escape_xml_chars(item_data.get('Country', 'GB'))}</Country>")
        
        # PostalCode is required when using ShippingDetails
        if "PostalCode" in item_data:
            xml_parts.append(f"<PostalCode>{self._escape_xml_chars(item_data.get('PostalCode'))}</PostalCode>")
        
        # Add Site - required for eBay UK
        xml_parts.append(f"<Site>{self._escape_xml_chars(item_data.get('Site', 'UK'))}</Site>")
        
        # Dispatch time
        if "DispatchTimeMax" in item_data:
            xml_parts.append(f"<DispatchTimeMax>{self._escape_xml_chars(item_data.get('DispatchTimeMax'))}</DispatchTimeMax>")
        
        # Close Item element and request
        xml_parts.append("</Item>")
        xml_parts.append("</AddFixedPriceItemRequest>")
        
        # Build the final XML request
        xml_request = "\n".join(xml_parts)
        
        # For debugging
        logger.info(f"AddFixedPriceItem XML request (first 2000 chars):\n{xml_request[:2000]}...")
        
        response = await self._make_request("AddFixedPriceItem", xml_request)
        
        if not response or "AddFixedPriceItemResponse" not in response:
            logger.error("No response data from eBay")
            return {"success": False, "errors": ["No response received from eBay"]}
            
        result = response["AddFixedPriceItemResponse"]
        
        if result.get("Ack") in ["Success", "Warning"]:
            item_id = result.get("ItemID")
            if item_id:
                return {
                    "success": True,
                    "item_id": item_id,
                    "fees": result.get("Fees", {}),
                    "listing_url": f"https://{'sandbox.' if self.sandbox else ''}ebay.com/itm/{item_id}"
                }
        
        # If we get here, there was an error
        errors = result.get("Errors", [])
        if not isinstance(errors, list):
            errors = [errors]
            
        error_messages = []
        for error in errors:
            error_messages.append(error.get("LongMessage", "Unknown error"))
            
        return {
            "success": False,
            "errors": error_messages
        }

    def _get_paypal_email(self) -> str:
        """Get PayPal email address based on environment"""
        # In production use real email, in sandbox use sandbox email
        return "payments@londonvintage.co.uk" if not self.sandbox else "sandbox@example.com"

    def _escape_xml_chars(self, text):
        """
        Escape special characters in text to make it XML-safe
        
        Args:
            text: The text to escape
            
        Returns:
            The escaped text
        """
        if text is None:
            return ""
        if not isinstance(text, str):
            text = str(text)
        return xml_escape(text, entities={"'": "&apos;", "\"": "&quot;"})

    async def relist_item(self, item_id: str) -> Dict[str, Any]:
        """
        Relist an item that has been ended
        
        Args:
            item_id: Original item ID to relist
            
        Returns:
            Dict with new item ID and other details
        """
        xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
        <RelistItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
            <RequesterCredentials>
                <eBayAuthToken>{await self._get_auth_token()}</eBayAuthToken>
            </RequesterCredentials>
            <Item>
                <ItemID>{item_id}</ItemID>
            </Item>
        </RelistItemRequest>"""
        
        response_dict = await self._make_request('RelistItem', xml_request)
        return response_dict.get('RelistItemResponse', {})

    async def relist_fixed_price_item(self, item_id: str) -> Dict[str, Any]:
        """
        Relist a fixed-price item that has been ended.

        Use this for fixed-price listings, multi-item listings, or multi-variation listings.
        For auction-style listings, use relist_item() instead.

        Args:
            item_id: Original item ID to relist

        Returns:
            Dict with new item ID and other details
        """
        xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
        <RelistFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
            <RequesterCredentials>
                <eBayAuthToken>{await self._get_auth_token()}</eBayAuthToken>
            </RequesterCredentials>
            <Item>
                <ItemID>{item_id}</ItemID>
            </Item>
        </RelistFixedPriceItemRequest>"""

        response_dict = await self._make_request('RelistFixedPriceItem', xml_request)
        return response_dict.get('RelistFixedPriceItemResponse', {})

    async def create_similar_listing(self, original_item_id: str, append_to_title: str = "- Relisted") -> Dict[str, Any]:
        """
        Create a new listing based on an existing/ended item
        
        Args:
            original_item_id: Original item ID to copy details from
            append_to_title: Text to append to the original title (default: "- Relisted")
            
        Returns:
            Dict with new item ID and other details
        """
        logger.info(f"Creating similar listing based on item {original_item_id}")
        
        # Get the original item details
        original_item = await self.get_item_details(original_item_id)
        if not original_item:
            logger.error(f"Could not retrieve details for item {original_item_id}")
            raise EbayAPIError(f"Item details not found for {original_item_id}")
        
        # Extract critical fields with fallbacks
        title = original_item.get('Title', '')
        if append_to_title and title:
            title = f"{title} {append_to_title}"
            
        description = original_item.get('Description', '')
        category_id = original_item.get('PrimaryCategory', {}).get('CategoryID', '')
        start_price = original_item.get('StartPrice', {}).get('#text', '0.0')
        currency = original_item.get('StartPrice', {}).get('@currencyID', 'GBP')
        condition_id = original_item.get('ConditionID', '3000')  # 3000 is Used in Very Good condition
        quantity = original_item.get('Quantity', '1')
        
        # Get item specifics (important for eBay listing quality)
        item_specifics = []
        if 'ItemSpecifics' in original_item and 'NameValueList' in original_item['ItemSpecifics']:
            name_value_lists = original_item['ItemSpecifics']['NameValueList']
            if not isinstance(name_value_lists, list):
                name_value_lists = [name_value_lists]
            
            for nvl in name_value_lists:
                name = nvl.get('Name', '')
                value = nvl.get('Value', '')
                if name and value:
                    if isinstance(value, list):
                        value_xml = ""
                        for v in value:
                            value_xml += f"<Value>{v}</Value>\n"
                        item_specifics.append(f"<NameValueList><Name>{name}</Name>{value_xml}</NameValueList>")
                    else:
                        item_specifics.append(f"<NameValueList><Name>{name}</Name><Value>{value}</Value></NameValueList>")
        
        item_specifics_xml = "\n".join(item_specifics)
        
        # Get pictures
        picture_urls = []
        if 'PictureDetails' in original_item and 'PictureURL' in original_item['PictureDetails']:
            urls = original_item['PictureDetails']['PictureURL']
            if isinstance(urls, str):
                picture_urls = [urls]
            else:
                picture_urls = urls
        
        # Format pictures for XML
        picture_xml = ""
        for url in picture_urls:
            picture_xml += f"<PictureURL>{url}</PictureURL>\n"
        
        # Get shipping details
        shipping_service = "UK_OtherCourier24"  # Default to generic courier
        shipping_cost = "25.00"  # Default cost
        
        if 'ShippingDetails' in original_item:
            shipping_details = original_item.get('ShippingDetails', {})
            if 'ShippingServiceOptions' in shipping_details:
                options = shipping_details['ShippingServiceOptions']
                if isinstance(options, list) and len(options) > 0:
                    shipping_service = options[0].get('ShippingService', shipping_service)
                    cost = options[0].get('ShippingServiceCost', {})
                    if '#text' in cost:
                        shipping_cost = cost['#text']
                elif isinstance(options, dict):
                    shipping_service = options.get('ShippingService', shipping_service)
                    cost = options.get('ShippingServiceCost', {})
                    if '#text' in cost:
                        shipping_cost = cost['#text']
        
        # Get return policy
        returns_accepted = "ReturnsAccepted"
        refund_option = "MoneyBack"
        returns_within = "Days_30"
        shipping_cost_paid_by = "Buyer"
        
        if 'ReturnPolicy' in original_item:
            policy = original_item['ReturnPolicy']
            returns_accepted = policy.get('ReturnsAcceptedOption', returns_accepted)
            refund_option = policy.get('RefundOption', refund_option)
            returns_within = policy.get('ReturnsWithinOption', returns_within)
            shipping_cost_paid_by = policy.get('ShippingCostPaidByOption', shipping_cost_paid_by)
        
        # Create XML for the request
        xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
        <AddItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
            <RequesterCredentials>
                <eBayAuthToken>{await self._get_auth_token()}</eBayAuthToken>
            </RequesterCredentials>
            <Item>
                <Title>{title}</Title>
                <Description><![CDATA[{description}]]></Description>
                <PrimaryCategory>
                    <CategoryID>{category_id}</CategoryID>
                </PrimaryCategory>
                <StartPrice>{start_price}</StartPrice>
                <Currency>{currency}</Currency>
                <Country>{original_item.get('Country', 'GB')}</Country>
                <DispatchTimeMax>3</DispatchTimeMax>
                <ListingDuration>GTC</ListingDuration>
                <ListingType>FixedPriceItem</ListingType>
                <ItemSpecifics>
                    {item_specifics_xml}
                </ItemSpecifics>
                <PictureDetails>
                    {picture_xml}
                </PictureDetails>
                <Quantity>{quantity}</Quantity>
                <ConditionID>{condition_id}</ConditionID>
                <Location>{original_item.get('Location', 'London, UK')}</Location>
                <ReturnPolicy>
                    <ReturnsAcceptedOption>{returns_accepted}</ReturnsAcceptedOption>
                    <RefundOption>{refund_option}</RefundOption>
                    <ReturnsWithinOption>{returns_within}</ReturnsWithinOption>
                    <ShippingCostPaidByOption>{shipping_cost_paid_by}</ShippingCostPaidByOption>
                </ReturnPolicy>
                <ShippingDetails>
                    <ShippingType>Flat</ShippingType>
                    <ShippingServiceOptions>
                        <ShippingServicePriority>1</ShippingServicePriority>
                        <ShippingService>{shipping_service}</ShippingService>
                        <ShippingServiceCost>{shipping_cost}</ShippingServiceCost>
                    </ShippingServiceOptions>
                </ShippingDetails>
                <PaymentMethods>PayPal</PaymentMethods>
                <PayPalEmailAddress>{self._get_paypal_email()}</PayPalEmailAddress>
                <Site>UK</Site>
            </Item>
        </AddItemRequest>"""
        
        response_dict = await self._make_request('AddItem', xml_request)
        
        # Process the response
        if 'AddItemResponse' in response_dict:
            response = response_dict['AddItemResponse']
            if response.get('Ack') in ('Success', 'Warning'):
                new_item_id = response.get('ItemID')
                logger.info(f"Successfully created similar listing with ID {new_item_id}")
                
                # Handle warnings if present
                if response.get('Ack') == 'Warning' and 'Errors' in response:
                    warnings = response['Errors']
                    if not isinstance(warnings, list):
                        warnings = [warnings]
                    
                    for warning in warnings:
                        if warning.get('SeverityCode') == 'Warning':
                            logger.warning(f"Warning creating listing: {warning.get('LongMessage')}")
                
                return {
                    'success': True,
                    'item_id': new_item_id,
                    'listing_url': f"https://www.ebay.co.uk/itm/{new_item_id}",
                    'fees': response.get('Fees', {}),
                    'start_time': response.get('StartTime'),
                    'end_time': response.get('EndTime')
                }
            else:
                # Handle errors
                errors = response.get('Errors', [])
                if not isinstance(errors, list):
                    errors = [errors]
                    
                error_messages = []
                for error in errors:
                    error_messages.append(error.get('LongMessage', 'Unknown error'))
                    
                error_str = "; ".join(error_messages)
                logger.error(f"Failed to create similar listing: {error_str}")
                raise EbayAPIError(f"Failed to create similar listing: {error_str}")
        else:
            logger.error("Invalid response from AddItem request")
            raise EbayAPIError("Invalid response from eBay when creating listing")

    async def upload_pictures(self, image_paths: List[str]) -> List[str]:
        """
        Upload pictures to eBay Picture Service

        Args:
            image_paths: List of local file paths to upload

        Returns:
            List[str]: List of URLs to the uploaded images
        """
        picture_urls = []
        
        for path in image_paths:
            try:
                # Convert image to base64
                with open(path, "rb") as f:
                    image_data = base64.b64encode(f.read()).decode("utf-8")
                
                # Create upload request
                xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
                <UploadSiteHostedPicturesRequest xmlns="urn:ebay:apis:eBLBaseComponents">
                    <RequesterCredentials>
                        <eBayAuthToken>{await self._get_auth_token()}</eBayAuthToken>
                    </RequesterCredentials>
                    <PictureName>{os.path.basename(path)}</PictureName>
                    <PictureData>{image_data}</PictureData>
                </UploadSiteHostedPicturesRequest>"""
                
                # Make request
                response = await self._make_request("UploadSiteHostedPictures", xml_request)
                
                if response and "UploadSiteHostedPicturesResponse" in response:
                    response_data = response["UploadSiteHostedPicturesResponse"]
                    if response_data.get("Ack") in ["Success", "Warning"]:
                        url = response_data.get("SiteHostedPictureDetails", {}).get("FullURL")
                        if url:
                            picture_urls.append(url)
                
            except Exception as e:
                logger.error(f"Error uploading image {path}: {str(e)}")
        
        return picture_urls

    async def get_category_features(self, category_id: str) -> Dict[str, Any]:
        """
        Get category features including valid condition IDs for a specific category.
        
        Args:
            category_id: The eBay category ID
            
        Returns:
            Dict with category features including ConditionEnabled and ConditionValues
        """
        logger.info(f"Getting category features for category ID: {category_id}")
        
        request_xml = f"""<?xml version="1.0" encoding="utf-8"?>
        <GetCategoryFeaturesRequest xmlns="urn:ebay:apis:eBLBaseComponents">
            <CategoryID>{category_id}</CategoryID>
            <DetailLevel>ReturnAll</DetailLevel>
            <RequesterCredentials>
                <eBayAuthToken>{await self._get_auth_token()}</eBayAuthToken>
            </RequesterCredentials>
            <Version>{self.compatibility_level}</Version>
        </GetCategoryFeaturesRequest>"""
        
        try:
            response_dict = await self._make_request("GetCategoryFeatures", request_xml)
            
            if response_dict.get('GetCategoryFeaturesResponse', {}).get('Ack') == 'Success':
                category_raw = response_dict['GetCategoryFeaturesResponse'].get('Category', {})
                
                # Handle case where Category might be a list (multiple categories returned)
                if isinstance(category_raw, list):
                    # If multiple categories, find the one we requested
                    category_data = {}
                    for cat in category_raw:
                        if isinstance(cat, dict) and cat.get('CategoryID') == category_id:
                            category_data = cat
                            break
                    if not category_data:
                        # If we didn't find our category, just use the first one
                        category_data = category_raw[0] if category_raw else {}
                else:
                    category_data = category_raw
                
                # Ensure category_data is a dict
                if not isinstance(category_data, dict):
                    logger.warning(f"Unexpected category data format for {category_id}: {type(category_data)}")
                    category_data = {}
                
                # Extract condition information
                condition_info = {
                    'CategoryID': category_id,
                    'ConditionEnabled': category_data.get('ConditionEnabled', 'Disabled'),
                    'ConditionValues': category_data.get('ConditionValues', {})
                }
                
                # Parse condition values if present
                if condition_info['ConditionValues']:
                    # Debug: log the type and structure
                    logger.debug(f"ConditionValues type: {type(condition_info['ConditionValues'])}")
                    logger.debug(f"ConditionValues content: {condition_info['ConditionValues']}")
                    
                    # Handle case where ConditionValues might be a list directly
                    if isinstance(condition_info['ConditionValues'], list):
                        condition_values = condition_info['ConditionValues']
                    else:
                        condition_values = condition_info['ConditionValues'].get('Condition', [])
                        if not isinstance(condition_values, list):
                            condition_values = [condition_values]
                    
                    # Format conditions for easier use - handle both dict and non-dict items
                    valid_conditions = []
                    for cond in condition_values:
                        if cond:
                            if isinstance(cond, dict):
                                valid_conditions.append({
                                    'ID': cond.get('ID'),
                                    'DisplayName': cond.get('DisplayName')
                                })
                            else:
                                # If it's not a dict, log it for debugging
                                logger.warning(f"Unexpected condition format for category {category_id}: {type(cond)} - {cond}")
                    
                    condition_info['ValidConditions'] = valid_conditions
                
                logger.info(f"Found {len(condition_info.get('ValidConditions', []))} valid conditions for category {category_id}")
                return condition_info
                
            else:
                logger.error(f"Failed to get category features: {response_dict}")
                return {}
                
        except Exception as e:
            logger.error(f"Error getting category features: {e}")
            return {}

    async def get_shipping_options(self, country_code: str = "GB") -> List[Dict]:
        """
        Get available shipping services for the given country

        Args:
            country_code: Two-letter country code (default: GB)

        Returns:
            List[Dict]: List of available shipping services
        """
        xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
        <GeteBayDetailsRequest xmlns="urn:ebay:apis:eBLBaseComponents">
            <RequesterCredentials>
                <eBayAuthToken>{await self._get_auth_token()}</eBayAuthToken>
            </RequesterCredentials>
            <DetailName>ShippingServiceDetails</DetailName>
        </GeteBayDetailsRequest>"""

        response = await self._make_request("GeteBayDetails", xml_request)

        if not response or "GeteBayDetailsResponse" not in response:
            logger.error("No response data from eBay")
            return []

        details = response["GeteBayDetailsResponse"].get("ShippingServiceDetails", [])
        if not isinstance(details, list):
            details = [details]

        # Filter shipping services for the specified country
        filtered_services = []
        for service in details:
            valid_for = service.get("ValidForSellingFlow", "false")
            ship_to_locations = service.get("ShippingServiceAvailability", {}).get("ShipToLocation", [])
            
            if not isinstance(ship_to_locations, list):
                ship_to_locations = [ship_to_locations]
                
            # Include service if it's valid for selling and available for the country
            if valid_for == "true" and (country_code in ship_to_locations or "Worldwide" in ship_to_locations):
                filtered_services.append({
                    "id": service.get("ShippingService", ""),
                    "name": service.get("Description", ""),
                    "international": service.get("InternationalService", "false") == "true",
                    "carrier": service.get("ShippingCarrier", "")
                })

        return filtered_services

    async def get_user_profile(self, user_id: str = None) -> Dict:
        """
        Get eBay user profile information

        Args:
            user_id: eBay user ID (if None, gets the authenticated user's profile)

        Returns:
            Dict: User profile data
        """
        xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
        <GetUserRequest xmlns="urn:ebay:apis:eBLBaseComponents">
            <RequesterCredentials>
                <eBayAuthToken>{await self._get_auth_token()}</eBayAuthToken>
            </RequesterCredentials>
            <DetailLevel>ReturnAll</DetailLevel>
            {"<UserID>" + user_id + "</UserID>" if user_id else ""}
        </GetUserRequest>"""

        response = await self._make_request("GetUser", xml_request)

        if not response or "GetUserResponse" not in response:
            logger.error("No response data from eBay")
            return {}

        user_data = response["GetUserResponse"].get("User", {})
        return user_data

    async def get_user_info(self) -> Dict[str, Any]:
        """
        Get information about the authenticated user
        
        Returns:
            Dict: User information
        """
        print("*** ENTERED get_user_info() METHOD ***")
        xml_request = """<?xml version="1.0" encoding="utf-8"?>
        <GetUserRequest xmlns="urn:ebay:apis:eBLBaseComponents">
            <DetailLevel>ReturnAll</DetailLevel>
        </GetUserRequest>"""
        
        print("*** ABOUT TO CALL execute_call() ***")
        
        try:
            # response_dict = await self.execute_call('GetUser', xml_request)
            response_dict = await self._make_request('GetUser', xml_request)
            
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

    async def create_item_and_store_id(self, item_data, ids_file="data/ebay_item_ids.json"):
        """Create an item and store its ID locally"""
        import json
        import os
        from datetime import datetime
        
        # Create a copy of the item data with escaped text fields
        safe_item_data = item_data.copy()
        
        # Escape text fields
        if "Title" in safe_item_data:
            safe_item_data["Title"] = self._escape_xml_chars(safe_item_data["Title"])
        if "Description" in safe_item_data:
            safe_item_data["Description"] = safe_item_data["Description"]  # HTML descriptions are in CDATA blocks, so don't escape
        
        # Escape item specifics
        if "ItemSpecifics" in safe_item_data and isinstance(safe_item_data["ItemSpecifics"], dict):
            escaped_specifics = {}
            for name, value in safe_item_data["ItemSpecifics"].items():
                escaped_name = self._escape_xml_chars(name)
                if isinstance(value, list):
                    escaped_value = [self._escape_xml_chars(v) for v in value]
                else:
                    escaped_value = self._escape_xml_chars(value)
                escaped_specifics[escaped_name] = escaped_value
            safe_item_data["ItemSpecifics"] = escaped_specifics
        
        # Create the item
        result = await self.add_fixed_price_item(safe_item_data)
        
        # Create the item - this line was the first main line before special characters fix
        # result = await self.add_fixed_price_item(item_data)
        
        if not result.get("success", False):
            logger.error(f"Failed to create item: {result.get('errors', ['Unknown error'])}")
            return None
        
        item_id = result.get("item_id")
        
        # Create storage directory if it doesn't exist
        os.makedirs(os.path.dirname(ids_file), exist_ok=True)
        
        # Load existing IDs if file exists
        stored_ids = []
        if os.path.exists(ids_file):
            try:
                with open(ids_file, 'r') as f:
                    stored_data = json.load(f)
                    stored_ids = stored_data.get("item_ids", [])
            except Exception as e:
                logger.warning(f"Error reading stored IDs: {e}")
        
        # Add the new ID with metadata
        item_entry = {
            "item_id": item_id,
            "title": item_data.get("Title", "Unknown"),
            "created_at": datetime.now().isoformat(),
            "listing_url": result.get("listing_url"),
            "sandbox": self.sandbox
        }
        stored_ids.append(item_entry)
        
        # Save back to file
        with open(ids_file, 'w') as f:
            json.dump({"item_ids": stored_ids}, f, indent=2)
        
        logger.info(f"Item ID {item_id} stored in {ids_file}")
        return item_id

    async def get_stored_inventory(self, ids_file="data/ebay_item_ids.json", include_details=False):
        """
        Retrieve listings directly using stored IDs instead of inventory API
        """
        
        if not os.path.exists(ids_file):
            logger.warning(f"ID storage file not found: {ids_file}")
            return []
        
        try:
            # Load stored IDs
            with open(ids_file, 'r') as f:
                stored_data = json.load(f)
                stored_entries = stored_data.get("item_ids", [])
            
            # Filter for sandbox vs production based on current API mode
            filtered_entries = [entry for entry in stored_entries 
                            if entry.get("sandbox", False) == self.sandbox]
            
            logger.info(f"Found {len(filtered_entries)} stored item IDs for "
                    f"{'sandbox' if self.sandbox else 'production'}")
            
            # Retrieve each item directly
            items = []
            for entry in filtered_entries:
                item_id = entry.get("item_id")
                if not item_id:
                    continue
                    
                try:
                    item = await self.get_item_details(item_id)
                    if item:
                        # Check if the item is still active
                        status = item.get("SellingStatus", {}).get("ListingStatus")
                        if status == "Active":
                            if include_details:
                                # Item already has details since we retrieved with get_item_details
                                items.append(item)
                            else:
                                # Strip down to basic info if details not requested
                                basic_item = {
                                    "ItemID": item_id,
                                    "Title": item.get("Title"),
                                    "SellingStatus": item.get("SellingStatus"),
                                    "_listing_type": "active"
                                }
                                items.append(basic_item)
                        else:
                            logger.info(f"Item {item_id} is no longer active (status: {status})")
                    else:
                        logger.warning(f"Could not retrieve item {item_id}")
                except Exception as e:
                    logger.error(f"Error retrieving item {item_id}: {str(e)}")
            
            return items
        except Exception as e:
            logger.error(f"Error loading stored IDs: {str(e)}")
            return []

    async def save_inventory_to_json(self, include_active: bool = True, 
                                    include_sold: bool = False, 
                                    include_unsold: bool = False,
                                    include_details: bool = True,
                                    output_path: str = "data/ebay_inventory.json") -> Dict[str, Any]:
        """
        Retrieve all eBay listings and save them to a local JSON file
        
        Args:
            include_active: Whether to include active listings
            include_sold: Whether to include sold listings
            include_unsold: Whether to include unsold listings
            include_details: Whether to include detailed item information
            output_path: File path where the JSON will be saved
            
        Returns:
            Dict with summary statistics and file path
        """
        import json
        import os
        from datetime import datetime
        
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Get all listings
        logger.info(f"Retrieving eBay inventory (active={include_active}, sold={include_sold}, unsold={include_unsold})...")
        
        listings = await self.get_all_selling_listings(
            include_active=include_active,
            include_sold=include_sold,
            include_unsold=include_unsold,
            include_details=include_details
        )
        
        # Add metadata
        inventory_data = {
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "environment": "sandbox" if self.sandbox else "production",
                "active_count": len(listings.get('active', [])),
                "sold_count": len(listings.get('sold', [])),
                "unsold_count": len(listings.get('unsold', [])),
                "include_details": include_details
            },
            "listings": listings
        }
        
        # Save to JSON file
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(inventory_data, f, indent=2, default=str)
        
        logger.info(f"Saved {sum(len(listings.get(key, [])) for key in listings.keys())} listings to {output_path}")
        return {
            "file_path": os.path.abspath(output_path),
            "active_count": len(listings.get('active', [])),
            "sold_count": len(listings.get('sold', [])),
            "unsold_count": len(listings.get('unsold', [])),
            "total_count": sum(len(listings.get(key, [])) for key in listings.keys())
        }

    async def load_inventory_from_json(self, input_path: str = "data/ebay_inventory.json") -> Dict[str, Any]:
        """
        Load eBay listings from a previously saved JSON file
        
        Args:
            input_path: File path where the JSON is stored
            
        Returns:
            Dict with listings data and metadata
        """
        import json
        import os
        
        if not os.path.exists(input_path):
            logger.error(f"Inventory file not found: {input_path}")
            return {
                "success": False,
                "error": f"File not found: {input_path}"
            }
        
        try:
            with open(input_path, 'r', encoding='utf-8') as f:
                inventory_data = json.load(f)
            
            # Get counts
            active_count = len(inventory_data.get('listings', {}).get('active', []))
            sold_count = len(inventory_data.get('listings', {}).get('sold', []))
            unsold_count = len(inventory_data.get('listings', {}).get('unsold', []))
            total_count = active_count + sold_count + unsold_count
            
            logger.info(f"Loaded {total_count} listings from {input_path}")
            logger.info(f"  Active: {active_count}, Sold: {sold_count}, Unsold: {unsold_count}")
            
            return {
                "success": True,
                "data": inventory_data,
                "active_count": active_count,
                "sold_count": sold_count,
                "unsold_count": unsold_count,
                "total_count": total_count,
                "metadata": inventory_data.get('metadata', {})
            }
        except Exception as e:
            logger.error(f"Error loading inventory from {input_path}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }


    # The following methods were in your original uploaded trading.py but seem to be for REST API.
    # EbayTradingLegacyAPI is typically for XML. If these are indeed REST, they belong in EbayClient.
    # For now, I will instrument them here as they were in your trading.py.
    # If they are REST, the endpoint and auth method (Bearer token) would be different.
    # The `_make_request` in this class is for XML. A separate `_make_rest_request` would be needed.

    async def _make_inventory_request(self, method: str, path: str, params: Optional[Dict] = None, data: Optional[Dict] = None) -> Dict:
        """ Helper for REST Inventory API calls - assuming this was intended for a REST client """
        # print(f"DEBUG: EbayTradingLegacyAPI._make_inventory_request (WARNING: Seems like a REST call in XML API class) - Method: {method}, Path: {path}")
        # This method would need to use Bearer token and a different endpoint (e.g., from EbayClient)
        # For now, just a placeholder print. If these are used, they need proper REST implementation.
        logger.warning("_make_inventory_request called in EbayTradingLegacyAPI - this is likely incorrect for REST.")
        return {} # Placeholder
            
    async def get_inventory_items(self, limit=100, offset=0) -> Dict:
        """Get inventory items (Likely a REST API call)"""
        # print(f"DEBUG: EbayTradingLegacyAPI.get_inventory_items (WARNING: Seems like a REST call) - limit: {limit}, offset: {offset}")
        # This would be a call to Inventory API (REST)
        # params = {'limit': limit, 'offset': offset}
        # return await self._make_inventory_request('GET', 'inventory_item', params=params)
        return {} # Placeholder


class EbayAccountAPI:
    """Class for eBay Account API (REST) operations."""

    def __init__(self, sandbox: bool = False):
        self.auth_manager = EbayAuthManager(sandbox=sandbox)
        self.sandbox = sandbox
        self.endpoint = (
            "https://api.sandbox.ebay.com/sell/account/v1"
            if sandbox
            else "https://api.ebay.com/sell/account/v1"
        )

    async def _make_rest_request(self, method: str, path: str, params: Optional[Dict] = None) -> Dict:
        """Makes a generic REST request to the Account API."""
        url = f"{self.endpoint}{path}"
        token = await self.auth_manager.get_access_token()
        headers = {
            'Authorization': f'Bearer {token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.request(method, url, headers=headers, params=params)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logging.error(f"Account API Error: {e.response.status_code} - {e.response.text}")
                raise EbayAPIError(f"Account API call failed: {e.response.text}")
            except Exception as e:
                logging.error(f"An unexpected error occurred: {e}")
                raise EbayAPIError(str(e))

    async def get_business_policies(self) -> Dict[str, Any]:
        """
        Fetches all business policies (Payment, Return, and Shipping).
        """
        logging.info("Fetching eBay business policies...")
        params = {'marketplace_id': 'EBAY_GB'}
        
        # --- THIS IS THE CORRECTED LINE ---
        return await self._make_rest_request('GET', '/policy/business_policy', params=params)

