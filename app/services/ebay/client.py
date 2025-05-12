import logging
import httpx

from typing import Dict, List, Optional, Any

from app.core.exceptions import EbayAPIError
from app.services.ebay.auth import EbayAuthManager

logger = logging.getLogger(__name__)

class EbayClient:
    """
    Client for interacting with eBay APIs.
    Handles authentication and provides methods for common operations.
    """
    
    # eBay API endpoints
    INVENTORY_API = "https://api.ebay.com/sell/inventory/v1"
    FULFILLMENT_API = "https://api.ebay.com/sell/fulfillment/v1"
    
    def __init__(self, sandbox: bool = False):
        """Initialize with auth manager"""
        self.auth_manager = EbayAuthManager(sandbox=sandbox)
        self.sandbox = sandbox
        self.marketplace_id = "EBAY_GB"  # Default for UK
        
        # Set API endpoints
        if sandbox:
            self.INVENTORY_API = "https://api.sandbox.ebay.com/sell/inventory/v1"
            self.FULFILLMENT_API = "https://api.sandbox.ebay.com/sell/fulfillment/v1"
        else:
            self.INVENTORY_API = "https://api.ebay.com/sell/inventory/v1"
            self.FULFILLMENT_API = "https://api.ebay.com/sell/fulfillment/v1"
    
    async def _get_headers(self) -> Dict[str, str]:
        """Get headers with auth token for API requests"""
        token = await self.auth_manager.get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    
    async def get_inventory_items(self, limit: int = 100, offset: int = 0) -> Dict:
        """
        Get inventory items from eBay
        
        Args:
            limit: Maximum number of items to return
            offset: Starting position in result set
            
        Returns:
            Dict: Response data
            
        Raises:
            EbayAPIError: If the API request fails
        """
        headers = await self._get_headers()
        url = f"{self.INVENTORY_API}/inventory_item?limit={limit}&offset={offset}"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers)
                
                if response.status_code != 200:
                    logger.error(f"eBay API error: {response.text}")
                    raise EbayAPIError(f"Failed to get inventory items: {response.text}")
                
                return response.json()
                
        except httpx.RequestError as e:
            logger.error(f"Network error getting inventory items: {str(e)}")
            raise EbayAPIError(f"Network error getting inventory items: {str(e)}")
    
    async def get_inventory_item(self, sku: str) -> Dict:
        """
        Get a specific inventory item by SKU
        
        Args:
            sku: The SKU of the item
            
        Returns:
            Dict: Item data
            
        Raises:
            EbayAPIError: If the API request fails
        """
        headers = await self._get_headers()
        url = f"{self.INVENTORY_API}/inventory_item/{sku}"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers)
                
                if response.status_code != 200:
                    logger.error(f"eBay API error: {response.text}")
                    raise EbayAPIError(f"Failed to get inventory item {sku}: {response.text}")
                
                return response.json()
                
        except httpx.RequestError as e:
            logger.error(f"Network error getting inventory item: {str(e)}")
            raise EbayAPIError(f"Network error getting inventory item: {str(e)}")
    
    async def create_or_update_inventory_item(self, sku: str, item_data: Dict) -> bool:
        """
        Create or update an inventory item
        
        Args:
            sku: The SKU of the item
            item_data: Data for the inventory item
            
        Returns:
            bool: Success status
            
        Raises:
            EbayAPIError: If the API request fails
        """
        headers = await self._get_headers()
        url = f"{self.INVENTORY_API}/inventory_item/{sku}"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.put(url, headers=headers, json=item_data)
                
                if response.status_code not in (200, 201, 204):
                    logger.error(f"eBay API error: {response.text}")
                    raise EbayAPIError(f"Failed to create/update inventory item {sku}: {response.text}")
                
                return True
                
        except httpx.RequestError as e:
            logger.error(f"Network error creating/updating inventory item: {str(e)}")
            raise EbayAPIError(f"Network error creating/updating inventory item: {str(e)}")
    
    async def create_offer(self, offer_data: Dict) -> Dict:
        """
        Create an offer for an inventory item
        
        Args:
            offer_data: Data for the offer
            
        Returns:
            Dict: Response with offer ID
            
        Raises:
            EbayAPIError: If the API request fails
        """
        headers = await self._get_headers()
        url = f"{self.INVENTORY_API}/offer"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=offer_data)
                
                if response.status_code not in (200, 201):
                    logger.error(f"eBay API error: {response.text}")
                    raise EbayAPIError(f"Failed to create offer: {response.text}")
                
                return response.json()
                
        except httpx.RequestError as e:
            logger.error(f"Network error creating offer: {str(e)}")
            raise EbayAPIError(f"Network error creating offer: {str(e)}")
    
    async def publish_offer(self, offer_id: str) -> Dict:
        """
        Publish an offer to make it active on eBay
        
        Args:
            offer_id: The ID of the offer to publish
            
        Returns:
            Dict: Response with listing ID
            
        Raises:
            EbayAPIError: If the API request fails
        """
        headers = await self._get_headers()
        url = f"{self.INVENTORY_API}/offer/{offer_id}/publish"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers)
                
                if response.status_code != 200:
                    logger.error(f"eBay API error: {response.text}")
                    raise EbayAPIError(f"Failed to publish offer {offer_id}: {response.text}")
                
                return response.json()
                
        except httpx.RequestError as e:
            logger.error(f"Network error publishing offer: {str(e)}")
            raise EbayAPIError(f"Network error publishing offer: {str(e)}")
    
    async def update_inventory_item_quantity(self, sku: str, quantity: int) -> bool:
        """
        Update the quantity of an inventory item
        
        Args:
            sku: The SKU of the item
            quantity: The new quantity
            
        Returns:
            bool: Success status
            
        Raises:
            EbayAPIError: If the API request fails
        """
        # First get the current item to preserve other data
        try:
            current_item = await self.get_inventory_item(sku)
            
            # Update only the quantity
            current_item["availability"]["quantity"] = quantity
            
            # Put back the updated item
            return await self.create_or_update_inventory_item(sku, current_item)
            
        except EbayAPIError as e:
            # If the item doesn't exist, this will fail
            logger.error(f"Error updating inventory quantity: {str(e)}")
            raise
    
    async def get_categories(self, category_tree_id: str = "0") -> Dict:
        """
        Get eBay categories from a specific category tree
        
        Args:
            category_tree_id: The category tree ID (0 for US)
            
        Returns:
            Dict: Category tree data
            
        Raises:
            EbayAPIError: If the API request fails
        """
        headers = await self._get_headers()
        url = f"https://api.ebay.com/commerce/taxonomy/v1/category_tree/{category_tree_id}"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers)
                
                if response.status_code != 200:
                    logger.error(f"eBay API error: {response.text}")
                    raise EbayAPIError(f"Failed to get category tree: {response.text}")
                
                return response.json()
                
        except httpx.RequestError as e:
            logger.error(f"Network error getting categories: {str(e)}")
            raise EbayAPIError(f"Network error getting categories: {str(e)}")

    async def get_category_suggestions(self, query: str) -> List[Dict]:
        """
        Get category suggestions based on a query
        
        Args:
            query: The query string
            
        Returns:
            List[Dict]: List of suggested categories
            
        Raises:
            EbayAPIError: If the API request fails
        """
        headers = await self._get_headers()
        url = f"https://api.ebay.com/commerce/taxonomy/v1/category_tree/0/get_category_suggestions?q={query}"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers)
                
                if response.status_code != 200:
                    logger.error(f"eBay API error: {response.text}")
                    raise EbayAPIError(f"Failed to get category suggestions: {response.text}")
                
                return response.json().get('categorySuggestions', [])
                
        except httpx.RequestError as e:
            logger.error(f"Network error getting category suggestions: {str(e)}")
            raise EbayAPIError(f"Network error getting category suggestions: {str(e)}")

    async def get_category_aspects(self, category_id: str) -> Dict:
        """
        Get aspects (item specifics) for a category
        
        Args:
            category_id: The category ID
            
        Returns:
            Dict: Category aspect data
            
        Raises:
            EbayAPIError: If the API request fails
        """
        headers = await self._get_headers()
        url = f"https://api.ebay.com/commerce/taxonomy/v1/category_tree/0/get_item_aspects_for_category?category_id={category_id}"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers)
                
                if response.status_code != 200:
                    logger.error(f"eBay API error: {response.text}")
                    raise EbayAPIError(f"Failed to get category aspects: {response.text}")
                
                return response.json()
                
        except httpx.RequestError as e:
            logger.error(f"Network error getting category aspects: {str(e)}")
            raise EbayAPIError(f"Network error getting category aspects: {str(e)}")

    async def get_listing_policies(self) -> Dict:
        """
        Get account policies (payment, return, fulfillment)
        
        Returns:
            Dict: Policies data
            
        Raises:
            EbayAPIError: If the API request fails
        """
        headers = await self._get_headers()
        
        try:
            policies = {}
            
            # Get payment policies
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.ebay.com/sell/account/v1/payment_policy",
                    headers=headers
                )
                
                if response.status_code == 200:
                    policies['payment'] = response.json().get('paymentPolicies', [])
                else:
                    logger.error(f"eBay API error: {response.text}")
            
            # Get return policies
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.ebay.com/sell/account/v1/return_policy",
                    headers=headers
                )
                
                if response.status_code == 200:
                    policies['return'] = response.json().get('returnPolicies', [])
                else:
                    logger.error(f"eBay API error: {response.text}")
            
            # Get fulfillment policies
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.ebay.com/sell/account/v1/fulfillment_policy",
                    headers=headers
                )
                
                if response.status_code == 200:
                    policies['fulfillment'] = response.json().get('fulfillmentPolicies', [])
                else:
                    logger.error(f"eBay API error: {response.text}")
            
            return policies
                
        except httpx.RequestError as e:
            logger.error(f"Network error getting listing policies: {str(e)}")
            raise EbayAPIError(f"Network error getting listing policies: {str(e)}")

    async def delete_inventory_item(self, sku: str) -> bool:
        """
        Delete an inventory item
        
        Args:
            sku: The SKU of the item
            
        Returns:
            bool: Success status
            
        Raises:
            EbayAPIError: If the API request fails
        """
        headers = await self._get_headers()
        url = f"{self.INVENTORY_API}/inventory_item/{sku}"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.delete(url, headers=headers)
                
                if response.status_code not in (200, 204):
                    logger.error(f"eBay API error: {response.text}")
                    raise EbayAPIError(f"Failed to delete inventory item {sku}: {response.text}")
                
                return True
                
        except httpx.RequestError as e:
            logger.error(f"Network error deleting inventory item: {str(e)}")
            raise EbayAPIError(f"Network error deleting inventory item: {str(e)}")

    async def get_offers(self, sku: str = None) -> Dict:
        """
        Get offers, optionally filtered by SKU
        
        Args:
            sku: Optional SKU to filter by
            
        Returns:
            Dict: Offers data
            
        Raises:
            EbayAPIError: If the API request fails
        """
        headers = await self._get_headers()
        url = f"{self.INVENTORY_API}/offer"
        if sku:
            url += f"?sku={sku}"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers)
                
                if response.status_code != 200:
                    logger.error(f"eBay API error: {response.text}")
                    raise EbayAPIError(f"Failed to get offers: {response.text}")
                
                return response.json()
                
        except httpx.RequestError as e:
            logger.error(f"Network error getting offers: {str(e)}")
            raise EbayAPIError(f"Network error getting offers: {str(e)}")

    async def delete_offer(self, offer_id: str) -> bool:
        """
        Delete an offer
        
        Args:
            offer_id: The ID of the offer
            
        Returns:
            bool: Success status
            
        Raises:
            EbayAPIError: If the API request fails
        """
        headers = await self._get_headers()
        url = f"{self.INVENTORY_API}/offer/{offer_id}"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.delete(url, headers=headers)
                
                if response.status_code not in (200, 204):
                    logger.error(f"eBay API error: {response.text}")
                    raise EbayAPIError(f"Failed to delete offer {offer_id}: {response.text}")
                
                return True
                
        except httpx.RequestError as e:
            logger.error(f"Network error deleting offer: {str(e)}")
            raise EbayAPIError(f"Network error deleting offer: {str(e)}")

    async def get_orders(self, limit: int = 50, offset: int = 0) -> Dict:
        """
        Get orders from eBay
        
        Args:
            limit: Maximum number of orders to return
            offset: Starting position in result set
            
        Returns:
            Dict: Orders data
            
        Raises:
            EbayAPIError: If the API request fails
        """
        headers = await self._get_headers()
        url = f"{self.FULFILLMENT_API}/order?limit={limit}&offset={offset}"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers)
                
                if response.status_code != 200:
                    logger.error(f"eBay API error: {response.text}")
                    raise EbayAPIError(f"Failed to get orders: {response.text}")
                
                return response.json()
                
        except httpx.RequestError as e:
            logger.error(f"Network error getting orders: {str(e)}")
            raise EbayAPIError(f"Network error getting orders: {str(e)}")

    async def get_order(self, order_id: str) -> Dict:
        """
        Get a specific order
        
        Args:
            order_id: The ID of the order
            
        Returns:
            Dict: Order data
            
        Raises:
            EbayAPIError: If the API request fails
        """
        headers = await self._get_headers()
        url = f"{self.FULFILLMENT_API}/order/{order_id}"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers)
                
                if response.status_code != 200:
                    logger.error(f"eBay API error: {response.text}")
                    raise EbayAPIError(f"Failed to get order {order_id}: {response.text}")
                
                return response.json()
                
        except httpx.RequestError as e:
            logger.error(f"Network error getting order: {str(e)}")
            raise EbayAPIError(f"Network error getting order: {str(e)}")
