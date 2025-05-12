# tests/unit/services/ebay/test_ebay_client.py
import pytest
import httpx
import json
from unittest.mock import patch, AsyncMock, MagicMock

from app.services.ebay.client import EbayClient
from app.services.ebay.auth import EbayAuthManager
from app.core.exceptions import EbayAPIError
from app.core.config import get_settings

settings = get_settings()

"""
1. Client Initialization Tests
"""

@pytest.mark.asyncio
async def test_ebay_client_initialization():
    """Test EbayClient initialization"""
    # Create client
    client = EbayClient()
    
    # Verify auth_manager was created
    assert client.auth_manager is not None
    assert isinstance(client.auth_manager, EbayAuthManager)
    
    # Verify API endpoints
    assert client.INVENTORY_API == "https://api.ebay.com/sell/inventory/v1"
    assert client.FULFILLMENT_API == "https://api.ebay.com/sell/fulfillment/v1"

"""
2. Header Generation Tests
"""

@pytest.mark.asyncio
async def test_get_headers(mocker):
    """Test header generation for API requests"""
    # Create client
    client = EbayClient()
    
    # Mock auth_manager.get_access_token
    client.auth_manager.get_access_token = AsyncMock(return_value="test-token")
    
    # Get headers
    headers = await client._get_headers()
    
    # Verify headers
    assert headers["Authorization"] == "Bearer test-token"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "application/json"

"""
3. Inventory Item Tests
"""

@pytest.mark.asyncio
async def test_get_inventory_items(mocker):
    """Test getting inventory items"""
    # Create client
    client = EbayClient()
    
    # Mock _get_headers with a proper AsyncMock
    mocker.patch.object(client, '_get_headers', AsyncMock(return_value={"Authorization": "Bearer test-token"}))
    
    # Create mock response with proper text property
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '{"inventoryItems": [...]}'
    mock_response.json.return_value = {
        "inventoryItems": [
            {"sku": "test-sku-1", "availability": {"quantity": 5}},
            {"sku": "test-sku-2", "availability": {"quantity": 10}}
        ],
        "total": 2
    }
    
    # Create a mock for the AsyncClient that correctly handles the async context manager
    async_client_mock = AsyncMock()
    async_client_mock.__aenter__.return_value.get.return_value = mock_response
    
    # Patch httpx.AsyncClient to return our async client mock
    mocker.patch('httpx.AsyncClient', return_value=async_client_mock)
    
    # Call get_inventory_items
    result = await client.get_inventory_items(limit=2, offset=0)
    
    # Verify result
    assert result["total"] == 2
    assert len(result["inventoryItems"]) == 2
    assert result["inventoryItems"][0]["sku"] == "test-sku-1"
    
    # Verify API call
    async_client_mock.__aenter__.return_value.get.assert_called_once()
    url_arg = async_client_mock.__aenter__.return_value.get.call_args[0][0]  # First positional argument is the URL
    assert 'limit=2' in url_arg
    assert 'offset=0' in url_arg


@pytest.mark.asyncio
async def test_get_inventory_item(mocker):
    """Test getting a specific inventory item"""
    # Create client
    client = EbayClient()
    
    # Mock _get_headers with a proper AsyncMock
    mocker.patch.object(client, '_get_headers', AsyncMock(return_value={"Authorization": "Bearer test-token"}))
    
    # Create mock response with proper text property
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '{"sku": "test-sku", ...}'
    mock_response.json.return_value = {
        "sku": "test-sku",
        "availability": {"quantity": 5},
        "product": {
            "title": "Test Product",
            "description": "Test description"
        }
    }
    
    # Create a mock for the AsyncClient that correctly handles the async context manager
    async_client_mock = AsyncMock()
    async_client_mock.__aenter__.return_value.get.return_value = mock_response
    
    # Patch httpx.AsyncClient to return our async client mock
    mocker.patch('httpx.AsyncClient', return_value=async_client_mock)
    
    # Call get_inventory_item
    result = await client.get_inventory_item("test-sku")
    
    # Verify result
    assert result["sku"] == "test-sku"
    assert result["availability"]["quantity"] == 5
    assert result["product"]["title"] == "Test Product"
    
    # Verify API call
    async_client_mock.__aenter__.return_value.get.assert_called_once()
    args, kwargs = async_client_mock.__aenter__.return_value.get.call_args
    url_arg = async_client_mock.__aenter__.return_value.get.call_args[0][0]
    assert 'test-sku' in url_arg


@pytest.mark.asyncio
async def test_create_or_update_inventory_item(mocker):
    """Test creating or updating inventory item"""
    # Create client
    client = EbayClient()
    
    # Mock _get_headers with AsyncMock
    mocker.patch.object(client, '_get_headers', AsyncMock(return_value={"Authorization": "Bearer test-token"}))

    # Create mock response with proper text property
    mock_response = MagicMock()
    mock_response.status_code = 204  # No content means success
    mock_response.text = "No content"  # Add this line

    # Create a mock for the AsyncClient that correctly handles the async context manager
    async_client_mock = AsyncMock()
    async_client_mock.__aenter__.return_value.put.return_value = mock_response

    # Patch httpx.AsyncClient to return our async client mock
    mocker.patch('httpx.AsyncClient', return_value=async_client_mock)
    
    # Create item data
    item_data = {
        "availability": {"quantity": 5},
        "product": {
            "title": "Test Product",
            "description": "Test description"
        }
    }
    
    # Call create_or_update_inventory_item
    result = await client.create_or_update_inventory_item("test-sku", item_data)
    
    # Verify result
    assert result is True
    
    # Verify API call
    async_client_mock.__aenter__.return_value.put.assert_called_once()
    args, kwargs = async_client_mock.__aenter__.return_value.put.call_args
    url_arg = async_client_mock.__aenter__.return_value.put.call_args[0][0]
    assert 'test-sku' in url_arg


"""
4. Error Handling Tests
"""


@pytest.mark.asyncio
async def test_inventory_api_error(mocker):
    """Test handling of inventory API errors"""
    # Create client
    client = EbayClient()
    
    # Mock _get_headers with a proper AsyncMock
    mocker.patch.object(client, '_get_headers', AsyncMock(return_value={"Authorization": "Bearer test-token"}))
    
    # Create mock response with proper text property for error case
    mock_response = MagicMock()
    mock_response.status_code = 400
    error_json = {"errors": [{"message": "Invalid request format"}]}
    mock_response.text = json.dumps(error_json)
    
    # Create a mock for the AsyncClient that correctly handles the async context manager
    async_client_mock = AsyncMock()
    async_client_mock.__aenter__.return_value.get.return_value = mock_response
    
    # Patch httpx.AsyncClient to return our async client mock
    mocker.patch('httpx.AsyncClient', return_value=async_client_mock)
    
    # Call method and verify it raises an exception
    with pytest.raises(EbayAPIError) as exc_info:
        await client.get_inventory_items()
    
    # Verify error message
    assert "Failed to get inventory items" in str(exc_info.value)
    assert json.dumps(error_json) in str(exc_info.value)


@pytest.mark.asyncio
async def test_network_error(mocker):
    """Test handling of network errors"""
    # Create client
    client = EbayClient()
    
    # Mock _get_headers with a proper AsyncMock
    mocker.patch.object(client, '_get_headers', AsyncMock(return_value={"Authorization": "Bearer test-token"}))
    
    # Create a mock for the AsyncClient that raises an exception
    async_client_mock = AsyncMock()
    async_client_mock.__aenter__.return_value.get.side_effect = httpx.RequestError("Connection error")
    
    # Patch httpx.AsyncClient to return our async client mock
    mocker.patch('httpx.AsyncClient', return_value=async_client_mock)
    
    # Call method and verify it raises an exception
    with pytest.raises(EbayAPIError) as exc_info:
        await client.get_inventory_items()
    
    # Verify error message
    assert "Network error getting inventory items" in str(exc_info.value)
    # Should include the original error message
    assert "Connection error" in str(exc_info.value)


"""
5. Offers Tests
"""

@pytest.mark.asyncio
async def test_create_offer(mocker):
    """Test creating an offer"""
    # Create client
    client = EbayClient()
    
    # Mock _get_headers with AsyncMock
    mocker.patch.object(client, '_get_headers', AsyncMock(return_value={"Authorization": "Bearer test-token"}))

    # Create mock response with proper text property
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.text = '{"offerId": "test-offer-id", "marketplaceId": "EBAY_GB"}'
    mock_response.json.return_value = {
        "offerId": "test-offer-id",
        "marketplaceId": "EBAY_GB"
    }

    # Create a mock for the AsyncClient that correctly handles the async context manager
    async_client_mock = AsyncMock()
    async_client_mock.__aenter__.return_value.post.return_value = mock_response

    # Patch httpx.AsyncClient to return our async client mock
    mocker.patch('httpx.AsyncClient', return_value=async_client_mock)
    
    # Create offer data
    offer_data = {
        "sku": "test-sku",
        "marketplaceId": "EBAY_GB",
        "format": "FIXED_PRICE",
        "availableQuantity": 5,
        "pricingSummary": {
            "price": {
                "currency": "GBP",
                "value": "100.00"
            }
        }
    }
    
    # Call create_offer
    result = await client.create_offer(offer_data)
    
    # Verify result
    assert result["offerId"] == "test-offer-id"
    assert result["marketplaceId"] == "EBAY_GB"
    
    # Verify API call
    async_client_mock.__aenter__.return_value.post.assert_called_once()
    url_arg = async_client_mock.__aenter__.return_value.post.call_args[0][0]
    assert f"{client.INVENTORY_API}/offer" in url_arg


@pytest.mark.asyncio
async def test_publish_offer(mocker):
    """Test publishing an offer"""
    # Create client
    client = EbayClient()
    
    # Mock _get_headers with AsyncMock
    mocker.patch.object(client, '_get_headers', AsyncMock(return_value={"Authorization": "Bearer test-token"}))
    
    # Create mock response with proper text property
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '{"listingId": "test-listing-id", "marketplaceId": "EBAY_GB"}'
    mock_response.json.return_value = {
        "listingId": "test-listing-id",
        "marketplaceId": "EBAY_GB"
    }
    
    # Create a mock for the AsyncClient that correctly handles the async context manager
    async_client_mock = AsyncMock()
    async_client_mock.__aenter__.return_value.post.return_value = mock_response
    
    # Patch httpx.AsyncClient to return our async client mock
    mocker.patch('httpx.AsyncClient', return_value=async_client_mock)
    
    # Call publish_offer
    result = await client.publish_offer("test-offer-id")
    
    # Verify result
    assert result["listingId"] == "test-listing-id"
    assert result["marketplaceId"] == "EBAY_GB"
    
    # Verify API call
    async_client_mock.__aenter__.return_value.post.assert_called_once()
    args, kwargs = async_client_mock.__aenter__.return_value.post.call_args
    url_arg = args[0]  # First positional argument is the URL
    assert "offer/test-offer-id/publish" in url_arg


"""
6. Inventory Update Tests
"""

@pytest.mark.asyncio
async def test_update_inventory_item_quantity(mocker):
    """Test updating inventory item quantity"""
    # Create client
    client = EbayClient()
    
    # Create item data
    current_item = {
        "sku": "test-sku",
        "availability": {"quantity": 5},
        "product": {
            "title": "Test Product",
            "description": "Test description"
        }
    }
    
    # Mock get_inventory_item to return item data
    mocker.patch.object(client, 'get_inventory_item', AsyncMock(return_value=current_item))

    # Mock create_or_update_inventory_item to return True
    mocker.patch.object(client, 'create_or_update_inventory_item', AsyncMock(return_value=True))
    
    # Call update_inventory_item_quantity
    result = await client.update_inventory_item_quantity("test-sku", 10)
    
    # Verify result
    assert result is True
    
    # Verify methods were called with correct arguments
    client.get_inventory_item.assert_called_once_with("test-sku")
    
    expected_update = current_item.copy()
    expected_update["availability"]["quantity"] = 10
    
    client.create_or_update_inventory_item.assert_called_once_with("test-sku", expected_update)

"""
7. Category Tests
"""


@pytest.mark.asyncio
async def test_get_category_suggestions(mocker):
    """Test getting category suggestions"""
    # Create client
    client = EbayClient()
    
    # Mock _get_headers with AsyncMock
    mocker.patch.object(client, '_get_headers', AsyncMock(return_value={"Authorization": "Bearer test-token"}))
    
    # Create mock response with proper text property
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '{"categorySuggestions": [...]}'
    mock_response.json.return_value = {
        "categorySuggestions": [
            {
                "category": {
                    "categoryId": "33034",
                    "categoryName": "Electric Guitars"
                }
            },
            {
                "category": {
                    "categoryId": "33021",
                    "categoryName": "Acoustic Guitars"
                }
            }
        ]
    }
    
    # Create a mock for the AsyncClient that correctly handles the async context manager
    async_client_mock = AsyncMock()
    async_client_mock.__aenter__.return_value.get.return_value = mock_response
    
    # Patch httpx.AsyncClient to return our async client mock
    mocker.patch('httpx.AsyncClient', return_value=async_client_mock)
    
    # Call get_category_suggestions
    result = await client.get_category_suggestions("guitar")
    
    # Verify result
    assert len(result) == 2
    assert result[0]["category"]["categoryId"] == "33034"
    assert result[1]["category"]["categoryName"] == "Acoustic Guitars"
    
    # Verify API call
    async_client_mock.__aenter__.return_value.get.assert_called_once()
    args, kwargs = async_client_mock.__aenter__.return_value.get.call_args
    url_arg = args[0]  # First positional argument is the URL
    assert "get_category_suggestions" in url_arg
    assert "q=guitar" in url_arg


"""
8. Orders Tests
"""

@pytest.mark.asyncio
async def test_get_orders(mocker):
    """Test getting orders"""
    # Create client
    client = EbayClient()
    
    # Mock _get_headers with AsyncMock
    mocker.patch.object(client, '_get_headers', AsyncMock(return_value={"Authorization": "Bearer test-token"}))
    
    # Create mock response with proper text property
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '{"orders": [...], "total": 2}'
    mock_response.json.return_value = {
        "orders": [
            {
                "orderId": "test-order-1",
                "orderStatus": "PAID"
            },
            {
                "orderId": "test-order-2",
                "orderStatus": "SHIPPED"
            }
        ],
        "total": 2
    }
    
    # Create a mock for the AsyncClient that correctly handles the async context manager
    async_client_mock = AsyncMock()
    async_client_mock.__aenter__.return_value.get.return_value = mock_response
    
    # Patch httpx.AsyncClient to return our async client mock
    mocker.patch('httpx.AsyncClient', return_value=async_client_mock)
    
    # Call get_orders
    result = await client.get_orders(limit=2, offset=0)
    
    # Verify result
    assert result["total"] == 2
    assert len(result["orders"]) == 2
    assert result["orders"][0]["orderId"] == "test-order-1"
    assert result["orders"][1]["orderStatus"] == "SHIPPED"
    
    # Verify API call
    async_client_mock.__aenter__.return_value.get.assert_called_once()
    args, kwargs = async_client_mock.__aenter__.return_value.get.call_args
    url_arg = args[0]  # First positional argument is the URL
    assert "order" in url_arg
    assert "limit=2" in url_arg
    assert "offset=0" in url_arg
    
