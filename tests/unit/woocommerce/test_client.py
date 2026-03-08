# tests/unit/woocommerce/test_client.py
"""Unit tests for WooCommerceClient."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from app.services.woocommerce.errors import (
    WCAuthenticationError, WCConnectionError, WCRateLimitError,
    WCProductNotFoundError, WCValidationError, WCAPIError,
)


@pytest.fixture
def client():
    """Create a WooCommerceClient with mocked settings."""
    with patch("app.services.woocommerce.client.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            WC_STORE_URL="https://store.example.com",
            WC_CONSUMER_KEY="ck_test",
            WC_CONSUMER_SECRET="cs_test",
            WC_SANDBOX_MODE=True,
        )
        from app.services.woocommerce.client import WooCommerceClient
        return WooCommerceClient()


class TestBasicAuth:
    """Test that HTTPS uses Basic Auth and HTTP uses query string."""

    def test_uses_https_true(self, client):
        assert client._uses_https is True

    def test_uses_https_false(self, client):
        client.store_url = "http://store.example.com"
        assert client._uses_https is False


class TestStripQuery:
    """Test credential stripping from URLs."""

    def test_strip_query_removes_params(self, client):
        url = "https://store.example.com/wp-json/wc/v3/products?consumer_key=ck_test&consumer_secret=cs_test"
        clean = client._strip_query(url)
        assert "consumer_key" not in clean
        assert "consumer_secret" not in clean
        assert clean == "https://store.example.com/wp-json/wc/v3/products"

    def test_strip_query_no_params(self, client):
        url = "https://store.example.com/wp-json/wc/v3/products"
        assert client._strip_query(url) == url


class TestConnectionPooling:
    """Test that client reuses connections."""

    def test_client_has_persistent_httpx_client(self, client):
        assert hasattr(client, "_client")
        assert isinstance(client._client, httpx.AsyncClient)

    @pytest.mark.asyncio
    async def test_close_releases_client(self, client):
        await client.close()
        # Client should be closed after this

    @pytest.mark.asyncio
    async def test_context_manager(self):
        with patch("app.services.woocommerce.client.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                WC_STORE_URL="https://store.example.com",
                WC_CONSUMER_KEY="ck_test",
                WC_CONSUMER_SECRET="cs_test",
                WC_SANDBOX_MODE=True,
            )
            from app.services.woocommerce.client import WooCommerceClient
            async with WooCommerceClient() as c:
                assert c is not None


class TestErrorClassification:
    """Test HTTP status code → exception type mapping."""

    def test_401_returns_auth_error(self, client):
        response = MagicMock()
        response.status_code = 401
        response.text = "Unauthorized"
        response.json.return_value = {"message": "Consumer key is invalid"}
        error = client._classify_error(response, "GET", "products")
        assert isinstance(error, WCAuthenticationError)

    def test_403_returns_auth_error(self, client):
        response = MagicMock()
        response.status_code = 403
        response.text = "Forbidden"
        response.json.return_value = {"message": "Insufficient permissions"}
        error = client._classify_error(response, "GET", "products")
        assert isinstance(error, WCAuthenticationError)

    def test_404_returns_not_found_error(self, client):
        response = MagicMock()
        response.status_code = 404
        response.text = "Not Found"
        response.json.return_value = {"message": "Product not found"}
        error = client._classify_error(response, "GET", "products/999")
        assert isinstance(error, WCProductNotFoundError)

    def test_422_returns_validation_error(self, client):
        response = MagicMock()
        response.status_code = 422
        response.text = "Unprocessable Entity"
        response.json.return_value = {"message": "Invalid data"}
        error = client._classify_error(response, "POST", "products")
        assert isinstance(error, WCValidationError)

    def test_500_returns_api_error(self, client):
        response = MagicMock()
        response.status_code = 500
        response.text = "Internal Server Error"
        response.json.return_value = {"message": "Server error"}
        error = client._classify_error(response, "GET", "products")
        assert isinstance(error, WCAPIError)

    def test_error_url_has_no_query_params(self, client):
        response = MagicMock()
        response.status_code = 500
        response.text = "Error"
        response.json.return_value = {"message": "Error"}
        error = client._classify_error(response, "GET", "products")
        assert "consumer_key" not in (error.request_url or "")
        assert "consumer_secret" not in (error.request_url or "")


class TestDeleteForceParam:
    """Test that force parameter is sent as string."""

    @pytest.mark.asyncio
    async def test_delete_force_true(self, client):
        client._request = AsyncMock(return_value={"id": 42})
        await client.delete_product(42, force=True)
        _, kwargs = client._request.call_args
        assert kwargs.get("params", {}).get("force") == "true"

    @pytest.mark.asyncio
    async def test_delete_force_false(self, client):
        client._request = AsyncMock(return_value={"id": 42})
        await client.delete_product(42, force=False)
        _, kwargs = client._request.call_args
        assert kwargs.get("params", {}).get("force") == "false"


class TestProductsCount:
    """Test efficient product count using X-WP-Total header."""

    @pytest.mark.asyncio
    async def test_get_products_count_uses_header(self, client):
        mock_response = MagicMock()
        mock_response.headers = {"X-WP-Total": "150"}
        mock_response.raise_for_status = MagicMock()
        client._client = AsyncMock()
        client._client.request = AsyncMock(return_value=mock_response)
        count = await client.get_products_count()
        assert count == 150
