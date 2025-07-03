import json
import logging
import httpx
import time
import math
import asyncio
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timezone

from app.core.exceptions import ReverbAPIError
from app.core.config import get_settings

logger = logging.getLogger(__name__)

class ReverbClient:
    """
    Purpose: Defines ReverbClient, an asynchronous client for interacting with the Reverb REST API (v3).
    
    Functionality: Handles authentication using the API key from settings and provides async methods (httpx) for common operations e.g.
                - Fetching categories (get_categories) and conditions (get_listing_conditions).
                - Listing management: creating (Notesing), updating (update_listing), getting details (get_listing, get_listing_details), publishing (publish_listing), ending (end_listing), 
                    finding by SKU (find_listing_by_sku).
                - Retrieving user-specific data: getting listings (get_my_listings, get_all_listings, get_all_listings_detailed with pagination), drafts (get_my_drafts), counts (get_my_counts), and importantly, sold orders (get_all_sold_orders with retries/error handling).
                - Image handling (currently placeholder/URL-based, noting direct file upload isn't implemented).
                - Includes robust base request logic (_make_request) with error handling (ReverbAPIError).
    
    Documentation: https://www.reverb-api.com/docs/   

    """
    
    PRODUCTION_BASE_URL = "https://api.reverb.com/api"
    SANDBOX_BASE_URL = "https://sandbox.reverb.com/api"
    
    def __init__(self, api_key: str, use_sandbox: bool = False):
        """
        Initialize the Reverb client
        
        Args:
            api_key: Reverb API key
            use_sandbox: Whether to use the sandbox environment
        """
        self.api_key = api_key
        self.use_sandbox = use_sandbox
        self.BASE_URL = self.SANDBOX_BASE_URL if use_sandbox else self.PRODUCTION_BASE_URL
        logger.info(f"Initializing ReverbClient with {'sandbox' if use_sandbox else 'production'} environment")
    
    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json", 
            "X-Display-Currency": "GBP",   # Tell the API to display prices in GBP
            "Accept-Version": "3.0"        # Use the latest API version
        }
    
    async def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        data: Optional[Dict] = None,
        params: Optional[Dict] = None, 
        timeout=30.0
    ) -> Dict:
        """
        Make a request to the Reverb API
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint (without base URL)
            data: Request payload for POST/PUT requests
            params: Query parameters
        
        Returns:
            Dict: Response data
        
        Raises:
            ReverbAPIError: If the API request fails
        """
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        headers = self._get_headers()
        
        # Log the request details for debugging (but hide the auth token)
        masked_headers = headers.copy()
        if "Authorization" in masked_headers:
            masked_headers["Authorization"] = "Bearer [REDACTED]"
            
        logger.debug(f"Making {method} request to {url}")
        logger.debug(f"Headers: {masked_headers}")
        
        logger.debug(f"Request URL: {url}")
        logger.debug(f"Request Headers: {masked_headers}")
        
        if params:
            logger.debug(f"Params: {params}")
        if data:
            logger.debug(f"Data: {json.dumps(data)[:500]}...")  # Log only first 500 chars of data
        
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=data,
                    params=params
                )
                
                if response.status_code not in (200, 201, 202, 204):
                    logger.error(f"Reverb API error: {response.text}")
                    raise ReverbAPIError(f"Request failed: {response.text}")
                
                if response.status_code == 204:  # No content
                    return {}
                
                return response.json()
        
        except httpx.RequestError as e:
            logger.error(f"Network error: {str(e)}")
            raise ReverbAPIError(f"Network error: {str(e)}")
        except httpx.TimeoutException as e:
            logger.error(f"Timeout error: {str(e)}")
            raise ReverbAPIError(f"Request timed out: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            raise ReverbAPIError(f"Unexpected error: {str(e)}")
    
    # Category operations
    
    async def get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """
        Make a GET request to the specified endpoint
        
        Args:
            endpoint: API endpoint (without base URL)
            
        Returns:
            Dict: Response data
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        return await self._make_request("GET", endpoint, params=params)
        
    async def get_categories(self) -> Dict:
        """
        Get all flat categories from Reverb
        
        Returns:
            Dict: Categories data
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        return await self._make_request("GET", "/categories/flat")
    
    async def get_category(self, uuid: str) -> Dict:
        """
        Get details for a specific category
        
        Args:
            uuid: Category UUID
            
        Returns:
            Dict: Category data
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        return await self._make_request("GET", f"/categories/{uuid}")
    
    # Condition operations
    
    async def get_listing_conditions(self) -> Dict:
        """
        Get all listing conditions from Reverb
        
        Returns:
            Dict: Listing conditions data
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        return await self._make_request("GET", "/listing_conditions")
    
    # Listing operations
    
    async def create_listing(self, listing_data: Dict) -> Dict:
        """
        Create a new listing on Reverb
        
        Args:
            listing_data: Complete listing data
            
        Returns:
            Dict: Created listing data including Reverb ID
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        return await self._make_request("POST", "/listings", data=listing_data)
    
    async def update_listing(self, listing_id: str, listing_data: Dict) -> Dict:
        """
        Update an existing listing on Reverb
        
        Args:
            listing_id: Reverb listing ID
            listing_data: Updated listing data
            
        Returns:
            Dict: Updated listing data
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        return await self._make_request("PUT", f"/listings/{listing_id}", data=listing_data)
    
    async def get_listing(self, listing_id: str, params: Optional[Dict] = None) -> Dict:
        """
        Get a specific listing's details
        
        Args:
            listing_id: Reverb listing ID
            params: Optional query parameters including currency
            
        Returns:
            Dict: Listing data
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        return await self._make_request("GET", f"/listings/{listing_id}", params=params)
    
    async def find_listing_by_sku(self, sku: str) -> Dict:
        """
        Find a listing by SKU
        
        Args:
            sku: Product SKU
            
        Returns:
            Dict: Listing data
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        return await self._make_request("GET", "/my/listings", params={"sku": sku, "state": "all"})
    
    async def publish_listing(self, listing_id: str) -> Dict:
        """
        Publish a draft listing
        
        Args:
            listing_id: Reverb listing ID
            
        Returns:
            Dict: Response data
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        return await self._make_request("PUT", f"/listings/{listing_id}", data={"publish": "true"})
    
    async def end_listing(self, listing_id: str, reason: str = "not_sold") -> Dict:
        """
        End a live listing
        
        Args:
            listing_id: Reverb listing ID
            reason: Reason for ending (not_sold or reverb_sale)
            
        Returns:
            Dict: Response data
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        return await self._make_request(
            "PUT", 
            f"/my/listings/{listing_id}/state/end", 
            data={"reason": reason}
        )
    
    async def get_my_drafts(self) -> Dict:
        """
        Get the authenticated user's draft listings
        
        Returns:
            Dict: Draft listings data
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        return await self._make_request("GET", "/my/listings/drafts")
    
    async def get_my_counts(self) -> Dict:
        """
        Get the authenticated user's listing counts by state
        
        Returns:
            Dict: Counts data
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        return await self._make_request("GET", "/my/counts")
    
    # Image operations
    
    async def upload_image_from_url(self, image_url: str) -> str:
        """
        Upload an image to Reverb from a URL
        
        Args:
            image_url: Public URL of the image
            
        Returns:
            str: Uploaded image URL on Reverb's servers
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        # Reverb accepts image URLs directly in listing creation
        # So we simply return the URL as-is for use in listing data
        return image_url
    
    async def upload_image_file(self, file_path: str) -> str:
        
        """
        Upload an image file to Reverb
        
        Note: This is a simplified placeholder that relies on the API accepting
        public URLs. For actual file uploads, Reverb's API documentation should
        be consulted for the proper upload method.
        
        Args:
            file_path: Path to local image file
            
        Raises:
            NotImplementedError: This method is not yet implemented
        """
        # This is a placeholder - actual implementation would depend on 
        # Reverb's API for direct file uploads or a two-step process:
        # 1. Upload to your own storage (S3, etc.)
        # 2. Use that public URL in Reverb listing
        raise NotImplementedError(
            "Direct file uploads not implemented. "
            "Please upload the image to a publicly accessible URL first, then use that URL."
        )
        
    async def get_my_listings(self, page: int = 1, per_page: int = 50, state: str = "all") -> Dict:
        """
        Get current user's listings from Reverb
        
        Args:
            page: Page number
            per_page: Items per page
            state: Listing state ('all', 'live', 'draft', 'sold', 'ended', 'suspended')
        """
        headers = self._get_headers()
        url = f"{self.BASE_URL}/my/listings?page={page}&per_page={per_page}&state={state}"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers)
                
                if response.status_code != 200:
                    logger.error(f"Reverb API error: {response.text}")
                    raise ReverbAPIError(f"Failed to get listings: {response.text}")
                
                return response.json()
        
        except httpx.RequestError as e:
            logger.error(f"Network error getting listings: {str(e)}")
            raise ReverbAPIError(f"Network error getting listings: {str(e)}")
        
    async def get_all_listings(self, state: str = "all") -> List[Dict]:
        """
        Get all listings by paginating through results

        Args:
            state: Listing state to fetch ('all', 'live', 'draft', 'sold', 'ended')

        Returns:
            List[Dict]: All listings
        """
        all_listings = []
        page = 1
        per_page = 50
        
        while True:
            response = await self.get_my_listings(page=page, per_page=per_page, state=state)
            listings = response.get('listings', [])
            
            if not listings:
                break
                
            all_listings.extend(listings)
            
            # Check if we've reached the last page
            total = response.get('total', 0)
            if page * per_page >= total:
                break
                
            page += 1
        
        return all_listings
    
    async def get_all_listings_detailed(self, max_concurrent: int = 10, state: str = "all") -> List[Dict]:
        """
        Get all listings with detailed information (handles pagination) using concurrent requests
        
        This enhanced version gets full listing details for each listing, which
        provides all the data we need for our enhanced schema.
        
        Args:
            max_concurrent: Maximum number of concurrent API calls (default: 10)
            state: Listing state to fetch ('all', 'live', 'draft', 'sold', 'ended')
        
        Returns:
            List[Dict]: All listings with full details
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        try:
            # First get the basic listings to get listing IDs
            basic_listings = await self.get_all_listings(state=state)
            logger.info(f"Got {len(basic_listings)} basic listings, fetching details...")
            
            # Create semaphore to limit concurrent requests
            semaphore = asyncio.Semaphore(max_concurrent)
            
            async def get_details_with_semaphore(listing):
                async with semaphore:
                    try:
                        listing_id = listing.get('id')
                        if listing_id:
                            detailed = await self.get_listing_details(str(listing_id))
                            return detailed
                        else:
                            logger.warning(f"Listing missing ID: {listing}")
                            return listing
                    except Exception as e:
                        logger.warning(f"Error getting details for listing {listing.get('id')}: {str(e)}")
                        return listing  # Return basic listing if details fail
            
            # Execute all detail requests concurrently
            logger.info(f"Starting {len(basic_listings)} concurrent detail requests (max {max_concurrent} at once)...")
            detailed_listings = await asyncio.gather(
                *[get_details_with_semaphore(listing) for listing in basic_listings],
                return_exceptions=True
            )
            
            # Filter out any exceptions and log them
            valid_listings = []
            for i, result in enumerate(detailed_listings):
                if isinstance(result, Exception):
                    logger.error(f"Failed to get details for listing {basic_listings[i].get('id')}: {result}")
                    valid_listings.append(basic_listings[i])  # Use basic listing as fallback
                else:
                    valid_listings.append(result)
            
            logger.info(f"Successfully retrieved details for {len(valid_listings)} listings")
            return valid_listings
            
        except Exception as e:
            logger.error(f"Error getting all listings with details: {str(e)}")
            raise ReverbAPIError(f"Failed to get all listings with details: {str(e)}")
        
        except Exception as e:
            logger.error(f"Error getting all listings with details: {str(e)}")
            raise ReverbAPIError(f"Failed to get all listings with details: {str(e)}")

    # Replace the existing get_listing_details method if it exists, or add this new one
    async def get_listing_details(self, listing_id: str) -> Dict:
        """
        Get detailed information for a specific listing
        
        Args:
            listing_id: Reverb listing ID
            
        Returns:
            Dict: Full listing details
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        try:
            headers = self._get_headers()
            url = f"{self.BASE_URL}/listings/{listing_id}"
            
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers)
                
                if response.status_code != 200:
                    logger.error(f"Reverb API error: {response.text}")
                    raise ReverbAPIError(f"Failed to get listing details: {response.text}")
                
                data = response.json()
                
                # Debug log
                if 'slug' in data:
                    logger.info(f"Listing {listing_id} has slug: {data['slug']}")
                else:
                    # [logger.warning(f"Listing {listing_id} MISSING slug field")
                    logger.info(f"Available fields: {list(data.keys())}")
                
                return data
        
        except httpx.RequestError as e:
            logger.error(f"Network error getting listing details: {str(e)}")
            raise ReverbAPIError(f"Network error getting listing details: {str(e)}")
        
    # async def get_all_sold_orders(self, per_page=50, max_pages=None):
    #     """
    #     Get all sold orders from Reverb with improved reliability
        
    #     Args:
    #         per_page: Number of orders per page
    #         max_pages: Maximum number of pages to fetch (None for all)
            
    #     Returns:
    #         List of order objects
    #     """
    #     url = "/my/orders/selling/all"
    #     params = {"per_page": per_page}
        
    #     # First request to get total count and first page
    #     response = await self._make_request("GET", url, params=params, timeout=60.0)
    #     if not response:
    #         return []
        
    #     total = response.get('total', 0)
    #     orders = response.get('orders', [])
        
    #     # Calculate number of pages
    #     total_pages = (total + per_page - 1) // per_page
    #     if max_pages is not None:
    #         total_pages = min(total_pages, max_pages)
        
    #     logger.info(f"Found {total} sold orders across {total_pages} pages")
        
    #     # Fetch remaining pages with retry logic
    #     for page in range(2, total_pages + 1):
    #         logger.info(f"Fetching sold orders page {page}/{total_pages}")
    #         params["page"] = page
            
    #         # Add retry logic
    #         max_retries = 3
    #         retry_count = 0
    #         success = False
            
    #         while not success and retry_count < max_retries:
    #             try:
    #                 # Add a delay to avoid rate limiting (increase with each retry)
    #                 await asyncio.sleep(1 + retry_count)
                    
    #                 # Increase timeout for potentially slow responses
    #                 page_response = await self._make_request("GET", url, params=params, timeout=60.0)
                    
    #                 if page_response and 'orders' in page_response:
    #                     orders.extend(page_response['orders'])
    #                     success = True
    #                 else:
    #                     raise Exception("Invalid response format")
                        
    #             except Exception as e:
    #                 retry_count += 1
    #                 logger.warning(f"Error fetching page {page}, attempt {retry_count}/{max_retries}: {str(e)}")
                    
    #                 if retry_count >= max_retries:
    #                     logger.error(f"Failed to fetch page {page} after {max_retries} attempts")
    #                     # Continue with what we have instead of failing completely
    #                     break
                    
    #                 # Exponential backoff
    #                 await asyncio.sleep(retry_count * 2)
        
    #     logger.info(f"Successfully retrieved {len(orders)} sold orders")
    #     return orders
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    