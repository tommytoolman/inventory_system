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
from urllib.parse import urlparse, urlunparse

import httpx

from app.core.config import get_settings
from app.core.exceptions import WooCommerceAPIError
from app.services.woocommerce.errors import (
    WCAuthenticationError, WCConnectionError, WCRateLimitError,
    WCProductNotFoundError, WCValidationError, WCImageUploadError,
    WCAPIError,
)
from app.services.woocommerce.error_logger import wc_logger

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

        # Persistent connection pool — avoids creating a new client per request
        self._client = httpx.AsyncClient(
            timeout=30,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

        logger.info(f"WooCommerceClient initialised for {self.store_url} (sandbox={self.sandbox_mode})")

    async def close(self):
        """Close the underlying HTTP client and release connections."""
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    # ------------------------------------------------------------------
    # Low-level request helpers
    # ------------------------------------------------------------------

    @property
    def _uses_https(self) -> bool:
        """Check if the store URL uses HTTPS."""
        return self.store_url.startswith("https")

    @staticmethod
    def _strip_query(url: str) -> str:
        """Strip query parameters from a URL to avoid logging credentials."""
        parsed = urlparse(url)
        return urlunparse(parsed._replace(query=""))

    def _auth_params(self) -> Dict[str, str]:
        """Return query-string auth params (fallback for HTTP connections)."""
        return {
            "consumer_key": self.consumer_key,
            "consumer_secret": self.consumer_secret,
        }

    async def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        """
        Make an authenticated request to the WooCommerce API.

        For HTTPS connections, uses HTTP Basic Auth (credentials in header).
        For HTTP connections, falls back to query string auth as WooCommerce requires.

        Includes automatic retry with exponential backoff for:
        - Connection timeouts and network errors
        - 429 rate limiting
        - 5xx server errors

        Client errors (4xx except 429) are NOT retried.
        Raises specific WC exception types based on HTTP status code.
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        params = kwargs.pop("params", {})

        # HTTPS: use Basic Auth header (secure). HTTP: query string (WC requirement).
        auth = None
        if self._uses_https:
            auth = (self.consumer_key, self.consumer_secret)
        else:
            params.update(self._auth_params())

        timeout = kwargs.pop("timeout", 30)
        max_retries = kwargs.pop("max_retries", 3)

        last_error = None

        for attempt in range(max_retries + 1):
            is_last = (attempt == max_retries)

            # -- Make the request -----------------------------------------
            try:
                response = await self._client.request(
                    method, url, params=params, auth=auth, timeout=timeout, **kwargs
                )
            except httpx.TimeoutException:
                last_error = WCConnectionError(
                    f"Request timed out after {timeout}s: {method} {endpoint}",
                    operation=f"api_{endpoint.split('/')[0]}",
                    request_method=method,
                    request_url=self._strip_query(url),
                    retry_count=attempt,
                )
                if not is_last:
                    wait = min(2 ** attempt, 10)
                    logger.warning(
                        f"Timeout on {method} {endpoint}, "
                        f"retry {attempt + 1}/{max_retries} in {wait}s"
                    )
                    await asyncio.sleep(wait)
                    continue
                wc_logger.log_error(last_error)
                raise last_error

            except httpx.RequestError as exc:
                last_error = WCConnectionError(
                    f"Network error: {exc}",
                    operation=f"api_{endpoint.split('/')[0]}",
                    request_method=method,
                    request_url=self._strip_query(url),
                    retry_count=attempt,
                )
                if not is_last:
                    wait = min(2 ** attempt, 10)
                    logger.warning(
                        f"Network error on {method} {endpoint}, "
                        f"retry {attempt + 1}/{max_retries} in {wait}s"
                    )
                    await asyncio.sleep(wait)
                    continue
                wc_logger.log_error(last_error)
                raise last_error

            # -- Handle response ------------------------------------------

            # Rate limiting -- always retry
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 60))
                if not is_last:
                    logger.warning(
                        f"Rate limited on {method} {endpoint}, "
                        f"retry after {retry_after}s"
                    )
                    await asyncio.sleep(retry_after)
                    continue
                error = WCRateLimitError(
                    f"Rate limited after {max_retries} retries: "
                    f"{method} {endpoint}",
                    retry_after=retry_after,
                    request_method=method,
                    request_url=self._strip_query(url),
                    http_status=429,
                    retry_count=attempt,
                )
                wc_logger.log_error(error)
                raise error

            # Server errors (5xx) -- retry
            if response.status_code >= 500:
                error = self._classify_error(response, method, endpoint, attempt)
                if not is_last:
                    wait = min(2 ** attempt, 10)
                    logger.warning(
                        f"Server error {response.status_code} on "
                        f"{method} {endpoint}, "
                        f"retry {attempt + 1}/{max_retries} in {wait}s"
                    )
                    await asyncio.sleep(wait)
                    last_error = error
                    continue
                wc_logger.log_error(error)
                raise error

            # Client errors (4xx) -- do NOT retry
            if response.status_code >= 400:
                error = self._classify_error(response, method, endpoint, attempt)
                wc_logger.log_error(error)
                raise error

            # -- Success --------------------------------------------------
            return response.json()

        # Safety net (should not reach here)
        if last_error:
            wc_logger.log_error(last_error)
            raise last_error
        raise WCAPIError(
            f"Request failed after {max_retries} retries: {method} {endpoint}"
        )

    def _classify_error(self, response, method: str, endpoint: str,
                        attempt: int = 0):
        """Map an HTTP error response to a specific WC exception type."""
        status = response.status_code
        body_text = response.text

        # Try to extract message from JSON response body
        message = body_text
        try:
            body_json = response.json()
            message = body_json.get("message", body_text)
        except Exception:
            pass

        clean_url = self._strip_query(f"{self.base_url}/{endpoint.lstrip('/')}")
        common = {
            "http_status": status,
            "request_method": method,
            "request_url": clean_url,
            "response_body": body_text[:2000],
            "retry_count": attempt,
            "operation": f"api_{method.lower()}_{endpoint.split('/')[0]}",
        }

        if status in (401, 403):
            return WCAuthenticationError(
                f"Authentication failed ({status}): {message}", **common
            )

        if status == 404:
            return WCProductNotFoundError(
                f"Not found: {method} {endpoint} -- {message}", **common
            )

        if status in (400, 422):
            msg_lower = message.lower() if isinstance(message, str) else ""
            if "image" in msg_lower:
                return WCImageUploadError(
                    f"Image error: {message}", **common
                )
            if any(kw in msg_lower for kw in ("sku", "duplicate", "already exists")):
                return WCValidationError(
                    f"Duplicate / invalid SKU: {message}", **common
                )
            return WCValidationError(
                f"Validation error ({status}): {message}", **common
            )

        # 5xx and anything else
        return WCAPIError(
            f"API error {status} on {method} {endpoint}: {message}", **common
        )

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
        return await self._request("DELETE", f"products/{product_id}", params={"force": "true" if force else "false"})

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
        """Get total number of products using the X-WP-Total header."""
        response = await self._request_raw("GET", "products", params={"per_page": 1})
        return int(response.headers.get("X-WP-Total", 0))

    async def _request_raw(self, method: str, endpoint: str, **kwargs) -> httpx.Response:
        """Make an authenticated request and return the raw httpx Response object."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        params = kwargs.pop("params", {})
        auth = None
        if self._uses_https:
            auth = (self.consumer_key, self.consumer_secret)
        else:
            params.update(self._auth_params())
        timeout = kwargs.pop("timeout", 30)
        response = await self._client.request(
            method, url, params=params, auth=auth, timeout=timeout, **kwargs
        )
        response.raise_for_status()
        return response

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
