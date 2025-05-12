# tests/unit/integrations/platforms/test_ebay_platform.py
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timezone, timedelta
from sqlalchemy import select

from app.integrations.platforms.ebay import EbayPlatform
from app.integrations.base import SyncStatus
from app.models.platform_common import PlatformCommon, ListingStatus
from app.models.ebay import EbayListing
from app.models.product import Product

"""
1. Platform Interface Tests
"""

@pytest.mark.asyncio
async def test_ebay_platform_initialization():
    """Test initialization of EbayPlatform"""
    platform = EbayPlatform()
    assert platform is not None
    assert platform._sync_status == SyncStatus.PENDING


@pytest.mark.asyncio
async def test_update_stock_success(db_session, mocker):
    """Test updating stock successfully"""
    # Create platform
    platform = EbayPlatform()
    
    # Mock the API call to eBay
    mock_update = AsyncMock(return_value=True)
    mocker.patch.object(platform, '_update_ebay_inventory', side_effect=mock_update)
    
    # Create product and eBay listing records
    product = Product(
        sku="EBAY-TEST-123",
        brand="Test Brand",
        model="Test Model",
        status="ACTIVE"
    )
    db_session.add(product)
    await db_session.flush()
    
    platform_common = PlatformCommon(
        product_id=product.id,
        platform_name="ebay",
        status=ListingStatus.ACTIVE.value,
        sync_status="SUCCESS"
    )
    db_session.add(platform_common)
    await db_session.flush()
    
    ebay_listing = EbayListing(
        platform_id=platform_common.id,
        ebay_sku="test-sku-123",
        quantity=1
    )
    db_session.add(ebay_listing)
    await db_session.flush()
    
    # Test updating stock
    result = await platform.update_stock(product.id, 5)
    
    # Verify result and API call
    assert result is True
    mock_update.assert_called_once_with(product.id, 5)
    
    # Verify last_sync was updated
    assert platform._last_sync is not None
    assert platform._sync_status == SyncStatus.SUCCESS


@pytest.mark.asyncio
async def test_update_stock_failure(db_session, mocker):
    """Test error handling when updating stock"""
    # Create platform
    platform = EbayPlatform()
    
    # Mock the API call to fail
    mock_update = AsyncMock(side_effect=Exception("API Error"))
    mocker.patch.object(platform, '_update_ebay_inventory', side_effect=mock_update)
    
    # Create product
    product = Product(
        sku="EBAY-TEST-FAIL",
        brand="Test Brand",
        model="Test Model",
        status="ACTIVE"
    )
    db_session.add(product)
    await db_session.flush()
    
    # Test updating stock
    result = await platform.update_stock(product.id, 5)
    
    # Verify result and error status
    assert result is False
    assert platform._sync_status == SyncStatus.ERROR


@pytest.mark.asyncio
async def test_get_current_stock_success(db_session, mocker):
    """Test getting current stock successfully"""
    # Create platform
    platform = EbayPlatform()
    
    # Mock the API call to eBay
    mock_get_stock = AsyncMock(return_value=10)
    mocker.patch.object(platform, '_get_ebay_inventory', side_effect=mock_get_stock)
    
    # Create product
    product = Product(
        sku="EBAY-STOCK-GET",
        brand="Test Brand",
        model="Test Model",
        status="ACTIVE"
    )
    db_session.add(product)
    await db_session.flush()
    
    # Test getting stock
    stock = await platform.get_current_stock(product.id)
    
    # Verify result
    assert stock == 10
    mock_get_stock.assert_called_once_with(product.id)


@pytest.mark.asyncio
async def test_get_current_stock_failure(db_session, mocker):
    """Test error handling when getting stock"""
    # Create platform
    platform = EbayPlatform()
    
    # Mock the API call to fail
    mock_get_stock = AsyncMock(side_effect=Exception("API Error"))
    mocker.patch.object(platform, '_get_ebay_inventory', side_effect=mock_get_stock)
    
    # Create product
    product = Product(
        sku="EBAY-STOCK-FAIL",
        brand="Test Brand",
        model="Test Model",
        status="ACTIVE"
    )
    db_session.add(product)
    await db_session.flush()
    
    # Test getting stock
    stock = await platform.get_current_stock(product.id)
    
    # Verify result is None on error
    assert stock is None
    assert platform._sync_status == SyncStatus.ERROR


@pytest.mark.asyncio
async def test_sync_status(db_session, mocker):
    """Test getting sync status"""
    # Create platform
    platform = EbayPlatform()
    
    # Set various states to test
    platform._sync_status = SyncStatus.SUCCESS
    platform._last_sync = datetime.now(timezone.utc)
    
    # Create product
    product = Product(
        sku="EBAY-SYNC-123",
        brand="Test Brand",
        model="Test Model",
        status="ACTIVE"
    )
    db_session.add(product)
    await db_session.flush()
    
    # Test getting sync status
    status = await platform.sync_status(product.id)
    
    # Verify correct status returned
    assert status == SyncStatus.SUCCESS
    
    # Test with an old sync time (more than 1 hour ago)
    platform._last_sync = datetime.now(timezone.utc) - timedelta(hours=2)
    status = await platform.sync_status(product.id)
    
    # Should indicate STALE status
    assert status == SyncStatus.STALE


"""
2. eBay-Specific Tests
"""

@pytest.mark.asyncio
async def test_update_ebay_inventory(db_session, mocker):
    """Test the eBay-specific inventory update method"""
    # Create platform
    platform = EbayPlatform()
    
    # Mock eBay API client
    mock_client = MagicMock()
    mock_client.update_inventory_item_quantity = AsyncMock(return_value=True)
    mocker.patch('app.integrations.platforms.ebay.EbayClient', return_value=mock_client)
    
    # Create product and eBay listing records
    product = Product(
        sku="EBAY-INVENTORY-123",
        brand="Test Brand",
        model="Test Model",
        status="ACTIVE"
    )
    db_session.add(product)
    await db_session.flush()
    
    platform_common = PlatformCommon(
        product_id=product.id,
        platform_name="ebay",
        status=ListingStatus.ACTIVE.value
    )
    db_session.add(platform_common)
    await db_session.flush()
    
    ebay_listing = EbayListing(
        platform_id=platform_common.id,
        ebay_sku="inventory-sku-123",
        quantity=1
    )
    db_session.add(ebay_listing)
    await db_session.flush()
    
    # Test the _update_ebay_inventory method (internal implementation)
    result = await platform._update_ebay_inventory(product.id, 15)
    
    # Verify result and API call
    assert result is True
    mock_client.update_inventory_item_quantity.assert_called_once_with("inventory-sku-123", 15)


@pytest.mark.asyncio
async def test_get_ebay_inventory(db_session, mocker):
    """Test the eBay-specific inventory retrieval method"""
    # Create platform
    platform = EbayPlatform()
    
    # Mock eBay API client
    mock_client = MagicMock()
    mock_response = {
        "availability": {
            "shipToLocationAvailability": {
                "quantity": 8
            }
        }
    }
    mock_client.get_inventory_item = AsyncMock(return_value=mock_response)
    mocker.patch('app.integrations.platforms.ebay.EbayClient', return_value=mock_client)
    
    # Create product and eBay listing records
    product = Product(
        sku="EBAY-GET-INV-123",
        brand="Test Brand",
        model="Test Model",
        status="ACTIVE"
    )
    db_session.add(product)
    await db_session.flush()
    
    platform_common = PlatformCommon(
        product_id=product.id,
        platform_name="ebay",
        status=ListingStatus.ACTIVE.value
    )
    db_session.add(platform_common)
    await db_session.flush()
    
    ebay_listing = EbayListing(
        platform_id=platform_common.id,
        ebay_sku="get-inv-sku-123",
        quantity=1
    )
    db_session.add(ebay_listing)
    await db_session.flush()
    
    # Test the _get_ebay_inventory method (internal implementation)
    quantity = await platform._get_ebay_inventory(product.id)
    
    # Verify result and API call
    assert quantity == 8
    mock_client.get_inventory_item.assert_called_once_with("get-inv-sku-123")


"""
3. Error Handling Tests
"""

@pytest.mark.asyncio
async def test_update_stock_no_listing(db_session):
    """Test updating stock when no listing exists"""
    # Create platform
    platform = EbayPlatform()
    
    # Create product but no eBay listing
    product = Product(
        sku="EBAY-NO-LISTING",
        brand="Test Brand",
        model="Test Model",
        status="ACTIVE"
    )
    db_session.add(product)
    await db_session.flush()
    
    # Test updating stock
    result = await platform.update_stock(product.id, 5)
    
    # Verify failure and error status
    assert result is False
    assert platform._sync_status == SyncStatus.ERROR


@pytest.mark.asyncio
async def test_rate_limiting_handling(db_session, mocker):
    """Test handling of rate limiting errors"""
    # Create platform
    platform = EbayPlatform()
    
    # Mock API to simulate rate limit first, then success
    call_count = 0
    
    async def mock_api_with_rate_limit(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call - simulate rate limit
            raise Exception("Rate limit exceeded")
        else:
            # Second call - success
            return True
    
    mocker.patch.object(platform, '_update_ebay_inventory', side_effect=mock_api_with_rate_limit)
    
    # Create product records
    product = Product(
        sku="EBAY-RATE-LIMIT",
        brand="Test Brand",
        model="Test Model",
        status="ACTIVE"
    )
    db_session.add(product)
    await db_session.flush()
    
    # Mock sleep to avoid actual waiting
    mocker.patch('asyncio.sleep', return_value=None)
    
    # Test updating stock with retry logic
    result = await platform.update_stock(product.id, 5)
    
    # Verify eventual success
    assert result is True
    assert call_count == 2  # Confirms retry happened
    assert platform._sync_status == SyncStatus.SUCCESS