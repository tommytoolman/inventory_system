# app/services/woocommerce/client.py
"""
WooCommerce REST API Client

Uses WooCommerce REST API v3 with Basic Authentication (sandbox) or
OAuth 1.0a (production). Follows the same async pattern as the
Reverb and Shopify clients.
"""

import logging
import asyncio
import time
from typing import Dict, List, Optional, Any

import httpx
from requests.auth import HTTPBasicAuth

from app.core.config import get_settings
from app.core.exceptions import WooCommerceAPIError

logger = logging.getLogger(__name__)


class WooCommerceClient:
    """
    Async client for WooCommerce REST API v3.

    Uses Basic Auth (consumer key / secret) over HTTPS.
    All methods are async for consistency with the rest of the codebase.
    """

    def __init__(self, store_url: Optional[str] = None, consumer_key: Optional[str] = None,
                 consumer_secret: Optional[str] = None):
        settings = get_settings()
        self.store_url = (store_url or settings.WC_STORE_URL or "").rstrip("/")
        self.consumer_key = consumer_key or settings.WC_CONSUMER_KEY or ""
        self.consumer_secret = consumer_secret or settings.WC_CONSUMER_SECRET or ""
        self.base_url = f"{self.store_url}/wp-json/wc/v3"
        self.sandbox_mode = settings.WC_SANDBOX_MODE

        if not self.store_url or not self.consumer_key or not self.consumer_secret:
            raise ValueError(
                "WooCommerce credentials not configured. "
                "Set WC_STORE_URL, WC_CONSUMER_KEY, WC_CONSUMER_SECRET in .env"
            )

        logger.info(f"WooCommerceClient initialised for {self.store_url} (sandbox={self.sandbox_mode})")

    # ------------------------------------------------------------------
    # Low-level request helpers
    # ------------------------------------------------------------------

    def _auth_params(self) -> Dict[str, str]:
        """Return query-string auth params (fallback if header auth fails)."""
        return {
            "consumer_key": self.consumer_key,
            "consumer_secret": self.consumer_secret,
        }

    async def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        """
        Make an authenticated request to the WooCommerce API.

        Tries Basic Auth header first. Falls back to query-string auth
        if the server cannot parse the header (common on some hosts).
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        # Merge auth params into query string (most reliable method)
        params = kwargs.pop("params", {})
        params.update(self._auth_params())

        timeout = kwargs.pop("timeout", 30)

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                response = await client.request(method, url, params=params, **kwargs)
            except httpx.TimeoutException as exc:
                raise WooCommerceAPIError(f"Request timed out: {url}") from exc
            except httpx.RequestError as exc:
                raise WooCommerceAPIError(f"Request failed: {exc}") from exc

        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            logger.warning(f"WooCommerce rate limit hit, retrying after {retry_after}s")
            await asyncio.sleep(retry_after)
            return await self._request(method, endpoint, params=params, **kwargs)

        if response.status_code >= 400:
            error_body = response.text
            try:
                error_json = response.json()
                error_body = error_json.get("message", error_body)
            except Exception:
                pass
            raise WooCommerceAPIError(
                f"WooCommerce API error {response.status_code} on {method} {endpoint}: {error_body}"
            )

        return response.json()

    # ------------------------------------------------------------------
    # Product endpoints
    # ------------------------------------------------------------------

    async def get_products(self, per_page: int = 100, page: int = 1,
                           **extra_params) -> List[Dict[str, Any]]:
        """Fetch a page of products."""
        params = {"per_page": per_page, "page": page, **extra_params}
        return await self._request("GET", "products", params=params)

    async def get_all_products(self, per_page: int = 100) -> List[Dict[str, Any]]:
        """Fetch all products with automatic pagination."""
        all_products = []
        page = 1
        while True:
            batch = await self.get_products(per_page=per_page, page=page)
            if not batch:
                break
            all_products.extend(batch)
            logger.info(f"Fetched page {page} ({len(batch)} products, total: {len(all_products)})")
            if len(batch) < per_page:
                break
            page += 1
        return all_products

    async def get_product(self, product_id: int) -> Dict[str, Any]:
        """Fetch a single product by its WooCommerce ID."""
        return await self._request("GET", f"products/{product_id}")

    async def create_product(self, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new product in WooCommerce."""
        logger.info(f"Creating WooCommerce product: {product_data.get('name', 'N/A')}")
        return await self._request("POST", "products", json=product_data)

    async def update_product(self, product_id: int, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing product."""
        logger.info(f"Updating WooCommerce product {product_id}")
        return await self._request("PUT", f"products/{product_id}", json=updates)

    async def delete_product(self, product_id: int, force: bool = False) -> Dict[str, Any]:
        """Delete a product (moves to trash by default, force=True permanently deletes)."""
        logger.info(f"Deleting WooCommerce product {product_id} (force={force})")
        return await self._request("DELETE", f"products/{product_id}", params={"force": force})

    async def batch_products(self, create: Optional[List] = None,
                             update: Optional[List] = None,
                             delete: Optional[List] = None) -> Dict[str, Any]:
        """Batch create/update/delete products."""
        payload = {}
        if create:
            payload["create"] = create
        if update:
            payload["update"] = update
        if delete:
            payload["delete"] = delete
        return await self._request("POST", "products/batch", json=payload)

    async def get_products_count(self) -> int:
        """Get total number of products."""
        products = await self.get_products(per_page=1)
        # WC API doesn't have a dedicated count endpoint; use the header approach
        # For now, do a full count via pagination
        return len(await self.get_all_products())

    # ------------------------------------------------------------------
    # Category endpoints
    # ------------------------------------------------------------------

    async def get_categories(self, per_page: int = 100) -> List[Dict[str, Any]]:
        """Fetch product categories."""
        return await self._request("GET", "products/categories", params={"per_page": per_page})

    # ------------------------------------------------------------------
    # Order endpoints
    # ------------------------------------------------------------------

    async def get_orders(self, per_page: int = 100, page: int = 1,
                         **extra_params) -> List[Dict[str, Any]]:
        """Fetch a page of orders."""
        params = {"per_page": per_page, "page": page, **extra_params}
        return await self._request("GET", "orders", params=params)

    async def get_all_orders(self, status: Optional[str] = None,
                             after: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch all orders with automatic pagination."""
        all_orders = []
        page = 1
        extra = {}
        if status:
            extra["status"] = status
        if after:
            extra["after"] = after
        while True:
            batch = await self.get_orders(per_page=100, page=page, **extra)
            if not batch:
                break
            all_orders.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return all_orders

    async def get_order(self, order_id: int) -> Dict[str, Any]:
        """Fetch a single order."""
        return await self._request("GET", f"orders/{order_id}")

    # ------------------------------------------------------------------
    # Webhook endpoints
    # ------------------------------------------------------------------

    async def create_webhook(self, name: str, topic: str,
                             delivery_url: str, secret: str) -> Dict[str, Any]:
        """Create a webhook in WooCommerce."""
        payload = {
            "name": name,
            "topic": topic,
            "delivery_url": delivery_url,
            "secret": secret,
        }
        return await self._request("POST", "webhooks", json=payload)

    async def get_webhooks(self) -> List[Dict[str, Any]]:
        """List all webhooks."""
        return await self._request("GET", "webhooks")

    # ------------------------------------------------------------------
    # System / diagnostics
    # ------------------------------------------------------------------

    async def get_system_status(self) -> Dict[str, Any]:
        """Fetch WooCommerce system status (useful for diagnostics)."""
        return await self._request("GET", "system_status")

    async def test_connection(self) -> bool:
        """Quick connectivity check. Returns True if API is reachable."""
        try:
            await self.get_products(per_page=1)
            return True
        except WooCommerceAPIError:
            return False
