import json
import logging
import httpx
import math
import asyncio
from typing import Dict, List, Optional, Any, Union
from datetime import datetime

from app.core.exceptions import ReverbAPIError
from app.core.config import get_settings

logger = logging.getLogger(__name__)

class ReverbClient:
    """
    Client for interacting with Reverb's REST API.
    Handles authentication and provides methods for common operations.
    
    Documentation: https://www.reverb-api.com/docs/
    
    Enhanced methods for the ReverbClient to better handle API responses with our new schema.
    This doesn't replace the entire client - just adds/updates methods that need to be modified.
    
    """
    
    # Base URL for Reverb API
    BASE_URL = "https://api.reverb.com/api"
    
    def __init__(self, api_key: str):
        """
        Initialize the Reverb client with an API key
        
        Args:
            api_key: Reverb API key (personal access token)
        """
        self.settings = get_settings()
        self.api_key = api_key
        
    
    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests with API key authentication"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/hal+json",
            "Accept": "application/hal+json",
            "Accept-Version": "3.0",
        }
    
    async def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        data: Optional[Dict] = None,
        params: Optional[Dict] = None
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
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=data,
                    params=params
                )
                
                if response.status_code not in (200, 201, 204):
                    logger.error(f"Reverb API error: {response.text}")
                    raise ReverbAPIError(f"Request failed: {response.text}")
                
                if response.status_code == 204:  # No content
                    return {}
                
                return response.json()
                
        except httpx.RequestError as e:
            logger.error(f"Network error: {str(e)}")
            raise ReverbAPIError(f"Network error: {str(e)}")
    
    # Category operations
    
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
    
    async def get_listing(self, listing_id: str) -> Dict:
        """
        Get a specific listing's details
        
        Args:
            listing_id: Reverb listing ID
            
        Returns:
            Dict: Listing data
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        return await self._make_request("GET", f"/listings/{listing_id}")
    
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
    
    # async def get_my_listings(self, page: int = 1, per_page: int = 50) -> Dict:
    #     """
    #     Get the authenticated user's listings with pagination
        
    #     Args:
    #         page: Page number (starting from 1)
    #         per_page: Number of listings per page (max 1000)
            
    #     Returns:
    #         Dict: Listings data with pagination info
            
    #     Raises:
    #         ReverbAPIError: If the API request fails
    #     """
    #     return await self._make_request(
    #         "GET", 
    #         "/my/listings", 
    #         params={"page": page, "per_page": per_page}
    #     )
    
    # async def get_all_my_listings(self) -> List[Dict]:
    #     """
    #     Get all of the authenticated user's listings (handles pagination)
        
    #     Returns:
    #         List[Dict]: All listings
            
    #     Raises:
    #         ReverbAPIError: If the API request fails
    #     """
    #     # Get first page to determine total pages
    #     first_page = await self.get_my_listings(page=1, per_page=50)
    #     total_items = first_page['total']
    #     total_pages = math.ceil(total_items / 50)
        
    #     # If only one page, return those listings
    #     if total_pages <= 1:
    #         return first_page['listings']
        
    #     # Otherwise, fetch all pages concurrently
    #     async def fetch_page(page_num):
    #         page_data = await self.get_my_listings(page=page_num, per_page=50)
    #         return page_data['listings']
        
    #     # Create tasks for remaining pages (we already have page 1)
    #     tasks = [fetch_page(page) for page in range(2, total_pages + 1)]
    #     other_pages_results = await asyncio.gather(*tasks)
        
    #     # Combine all listings (first page + all other pages)
    #     all_listings = first_page['listings']
    #     for page_listings in other_pages_results:
    #         all_listings.extend(page_listings)
        
    #     return all_listings
    
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
        
    async def get_my_listings(self, page: int = 1, per_page: int = 50) -> Dict:
        """
        Get current user's listings from Reverb
        """
        # Use the non-awaited version
        headers = self._get_headers()
        url = f"{self.BASE_URL}/my/listings?page={page}&per_page={per_page}"
        
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
    
    
    async def get_all_listings(self) -> List[Dict]:
        """
        Get all listings by paginating through results
        
        Returns:
            List[Dict]: All listings
        """
        all_listings = []
        page = 1
        per_page = 50
        
        while True:
            response = await self.get_my_listings(page=page, per_page=per_page)
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
    
    async def get_all_listings_detailed(self) -> List[Dict]:
        """
        Get all listings with detailed information (handles pagination)
        
        This enhanced version gets full listing details for each listing, which
        provides all the data we need for our enhanced schema.
        
        Returns:
            List[Dict]: All listings with full details
            
        Raises:
            ReverbAPIError: If the API request fails
        """
        try:
            # First get the basic listings to get listing IDs
            basic_listings = await self.get_all_listings()
            
            # Then fetch detailed information for each listing
            detailed_listings = []
            
            for listing in basic_listings:
                try:
                    listing_id = listing.get('id')
                    if listing_id:
                        details = await self.get_listing_details(listing_id)
                        detailed_listings.append(details)
                except Exception as e:
                    logger.warning(f"Error getting details for listing {listing.get('id')}: {str(e)}")
                    # Still include the basic listing to maintain the count
                    detailed_listings.append(listing)
            
            return detailed_listings
        
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
                
                return response.json()
        
        except httpx.RequestError as e:
            logger.error(f"Network error getting listing details: {str(e)}")
            raise ReverbAPIError(f"Network error getting listing details: {str(e)}")