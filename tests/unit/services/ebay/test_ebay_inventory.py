# tests/unit/services/ebay/test_ebay_inventory.py
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ebay.inventory import EbayInventoryManager
from app.services.ebay.client import EbayClient
from app.models.ebay import EbayListing
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.models.product import Product, ProductStatus
from app.core.exceptions import EbayAPIError

"""
1. Inventory Manager Initialization Tests
"""

@pytest.mark.asyncio
async def test_ebay_inventory_manager_initialization(db_session, mocker):
    """Test initialization of EbayInventoryManager"""
    # Mock settings
    mock_settings = mocker.MagicMock()
    mock_settings.EBAY_SANDBOX = False
    
    # Create inventory manager
    inventory_manager = EbayInventoryManager(db_session, mock_settings)
    
    # Verify attributes
    assert inventory_manager.db_session == db_session
    assert isinstance(inventory_manager.client, EbayClient)
    assert inventory_manager.client.sandbox is False

@pytest.mark.asyncio
async def test_ebay_inventory_manager_initialization_sandbox(db_session, mocker):
    """Test initialization of EbayInventoryManager in sandbox mode"""
    # Mock settings
    mock_settings = mocker.MagicMock()
    mock_settings.EBAY_SANDBOX = True
    
    # Create inventory manager
    inventory_manager = EbayInventoryManager(db_session, mock_settings, sandbox=True)
    
    # Verify attributes
    assert inventory_manager.client.sandbox is True

"""
2. Inventory Update Tests
"""

@pytest.mark.asyncio
async def test_update_inventory_item_success(db_session, mocker):
    """Test update_inventory_item method success"""
    # Create test product and listings
    product = Product(
        id=1,
        sku="TEST-SKU-001",
        brand="Test Brand",
        model="Test Model",
        description="Test Description",
        status=ProductStatus.ACTIVE.value,
        base_price=100.00,
        condition="EXCELLENT"
    )
    
    platform_common = PlatformCommon(
        id=1,
        product_id=1,
        platform_name="ebay",
        external_id="ext-123",
        status=ListingStatus.ACTIVE.value,
        sync_status=SyncStatus.SYNCED.value
    )
    
    ebay_listing = EbayListing(
        id=1,
        platform_id=1,
        ebay_item_id="item-123",
        ebay_sku="ebay-sku-123",
        quantity=5,
        format="FIXED_PRICE"
    )
    
    # Mock db_session.execute to return our test objects
    async def mock_execute(statement, *args, **kwargs):
        mock_result = MagicMock()
        if "Product" in str(statement):
            mock_result.scalar_one_or_none.return_value = product
        elif "PlatformCommon" in str(statement):
            mock_result.scalar_one_or_none.return_value = platform_common
            platform_common.product = product  # Set up relationship
        elif "EbayListing" in str(statement):
            mock_result.scalar_one_or_none.return_value = ebay_listing
            ebay_listing.platform_listing = platform_common  # Set up relationship
        return mock_result
    
    mocker.patch.object(db_session, 'execute', side_effect=mock_execute)
    mocker.patch.object(db_session, 'commit', AsyncMock())
    
    # Mock client update_inventory_item_quantity
    mock_client = MagicMock(spec=EbayClient)
    mock_client.update_inventory_item_quantity = AsyncMock(return_value=True)
    
    # Create inventory manager with mocked client
    inventory_manager = EbayInventoryManager(db_session, MagicMock())
    inventory_manager.client = mock_client
    
    # Call method
    result = await inventory_manager.update_inventory_item(1, 10)
    
    # Verify result
    assert result is True
    
    # Verify client was called
    mock_client.update_inventory_item_quantity.assert_called_once_with("ebay-sku-123", 10)
    
    # Verify database was updated
    assert ebay_listing.quantity == 10
    assert platform_common.sync_status == SyncStatus.SYNCED.value
    assert platform_common.last_synced_at is not None

@pytest.mark.asyncio
async def test_update_inventory_item_not_found(db_session, mocker):
    """Test update_inventory_item with non-existent listing"""
    # Mock db_session.execute to return None (not found)
    async def mock_execute(statement, *args, **kwargs):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        return mock_result
    
    mocker.patch.object(db_session, 'execute', side_effect=mock_execute)
    
    # Create inventory manager
    inventory_manager = EbayInventoryManager(db_session, MagicMock())
    
    # Call method and expect an exception
    with pytest.raises(ValueError) as exc_info:
        await inventory_manager.update_inventory_item(999, 10)
    
    # Verify the error message
    assert "not found" in str(exc_info.value)

@pytest.mark.asyncio
async def test_update_inventory_item_api_error(db_session, mocker):
    """Test update_inventory_item handling API errors"""
    # Create test objects
    product = Product(id=1, sku="TEST-SKU-001", status=ProductStatus.ACTIVE.value)
    platform_common = PlatformCommon(
        id=1,
        product_id=1,
        platform_name="ebay",
        external_id="ext-123",
        status=ListingStatus.ACTIVE.value
    )
    ebay_listing = EbayListing(
        id=1,
        platform_id=1,
        ebay_item_id="item-123",
        ebay_sku="ebay-sku-123",
        quantity=5
    )
    
    # Mock db_session.execute
    async def mock_execute(statement, *args, **kwargs):
        mock_result = MagicMock()
        if "EbayListing" in str(statement):
            mock_result.scalar_one_or_none.return_value = ebay_listing
            ebay_listing.platform_listing = platform_common
            platform_common.product = product
        return mock_result
    
    mocker.patch.object(db_session, 'execute', side_effect=mock_execute)
    mocker.patch.object(db_session, 'commit', AsyncMock())
    
    # Mock client to raise an API error
    mock_client = MagicMock(spec=EbayClient)
    mock_client.update_inventory_item_quantity = AsyncMock(side_effect=EbayAPIError("API Error"))
    
    # Create inventory manager with mocked client
    inventory_manager = EbayInventoryManager(db_session, MagicMock())
    inventory_manager.client = mock_client
    
    # Call method and expect an exception
    with pytest.raises(EbayAPIError) as exc_info:
        await inventory_manager.update_inventory_item(1, 10)
    
    # Verify the error message
    assert "API Error" in str(exc_info.value)
    
    # Verify sync status was updated to ERROR
    assert platform_common.sync_status == SyncStatus.ERROR.value
    assert platform_common.sync_message is not None
    assert "API Error" in platform_common.sync_message

"""
3. Inventory Sync Tests
"""

@pytest.mark.asyncio
async def test_sync_inventory_success(db_session, mocker):
    """Test sync_inventory method success"""
    # Create test products and listings
    products = [
        Product(id=1, sku="TEST-SKU-001", status=ProductStatus.ACTIVE.value),
        Product(id=2, sku="TEST-SKU-002", status=ProductStatus.ACTIVE.value)
    ]
    
    platform_commons = [
        PlatformCommon(
            id=1,
            product_id=1,
            platform_name="ebay",
            external_id="ext-123",
            status=ListingStatus.ACTIVE.value
        ),
        PlatformCommon(
            id=2,
            product_id=2,
            platform_name="ebay",
            external_id="ext-456",
            status=ListingStatus.ACTIVE.value
        )
    ]
    
    ebay_listings = [
        EbayListing(
            id=1,
            platform_id=1,
            ebay_item_id="item-123",
            ebay_sku="ebay-sku-123",
            quantity=5
        ),
        EbayListing(
            id=2,
            platform_id=2,
            ebay_item_id="item-456",
            ebay_sku="ebay-sku-456",
            quantity=10
        )
    ]
    
    # Set up relationships
    platform_commons[0].product = products[0]
    platform_commons[1].product = products[1]
    ebay_listings[0].platform_listing = platform_commons[0]
    ebay_listings[1].platform_listing = platform_commons[1]
    
    # Mock db_session.execute to return our listings
    async def mock_execute(statement, *args, **kwargs):
        mock_result = MagicMock()
        if "FROM ebay_listings" in str(statement):
            mock_result.scalars.return_value.all.return_value = ebay_listings
        return mock_result
    
    mocker.patch.object(db_session, 'execute', side_effect=mock_execute)
    mocker.patch.object(db_session, 'commit', AsyncMock())
    
    # Mock update_inventory_item
    mock_update = AsyncMock(return_value=True)
    mocker.patch.object(EbayInventoryManager, 'update_inventory_item', mock_update)
    
    # Create inventory manager
    inventory_manager = EbayInventoryManager(db_session, MagicMock())
    
    # Call method
    result = await inventory_manager.sync_inventory()
    
    # Verify result
    assert result["total"] == 2
    assert result["succeeded"] == 2
    assert result["failed"] == 0
    
    # Verify update_inventory_item was called for both listings
    assert mock_update.call_count == 2
    mock_update.assert_any_call(1, 5)
    mock_update.assert_any_call(2, 10)

@pytest.mark.asyncio
async def test_sync_inventory_partial_failure(db_session, mocker):
    """Test sync_inventory with partial failures"""
    # Create test listings
    listings = [
        MagicMock(id=1, quantity=5),
        MagicMock(id=2, quantity=10)
    ]
    
    # Mock db_session.execute
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = listings
    mocker.patch.object(db_session, 'execute', return_value=mock_result)
    
    # Mock update_inventory_item to succeed for first listing but fail for second
    async def mock_update(listing_id, quantity):
        if listing_id == 1:
            return True
        else:
            raise EbayAPIError("API Error for second listing")
    
    mocker.patch.object(EbayInventoryManager, 'update_inventory_item', side_effect=mock_update)
    
    # Create inventory manager
    inventory_manager = EbayInventoryManager(db_session, MagicMock())
    
    # Call method
    result = await inventory_manager.sync_inventory()
    
    # Verify result shows one success and one failure
    assert result["total"] == 2
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert len(result["errors"]) == 1
    assert "API Error for second listing" in result["errors"][0]

"""
4. Listing Creation/Update Tests
"""

@pytest.mark.asyncio
async def test_create_inventory_item_success(db_session, mocker):
    """Test create_inventory_item method success"""
    # Create test product and platform_common
    product = Product(
        id=1,
        sku="TEST-SKU-001",
        brand="Test Brand",
        model="Test Model",
        description="Test Description",
        status=ProductStatus.ACTIVE.value,
        base_price=100.00,
        condition="EXCELLENT"
    )
    
    platform_common = PlatformCommon(
        id=1,
        product_id=1,
        platform_name="ebay",
        external_id=None,  # No external ID yet
        status=ListingStatus.DRAFT.value,
        sync_status=SyncStatus.PENDING.value
    )
    
    # Mock db_session.execute
    async def mock_execute(statement, *args, **kwargs):
        mock_result = MagicMock()
        if "PlatformCommon" in str(statement):
            mock_result.scalar_one_or_none.return_value = platform_common
            platform_common.product = product
        return mock_result
    
    mocker.patch.object(db_session, 'execute', side_effect=mock_execute)
    mocker.patch.object(db_session, 'add', MagicMock())
    mocker.patch.object(db_session, 'commit', AsyncMock())
    
    # Mock client create_or_replace_inventory_item
    mock_client = MagicMock(spec=EbayClient)
    mock_client.create_or_replace_inventory_item = AsyncMock(return_value=True)
    
    # Create inventory manager with mocked client
    inventory_manager = EbayInventoryManager(db_session, MagicMock())
    inventory_manager.client = mock_client
    
    # Item data
    item_data = {
        "sku": "ebay-sku-new",
        "condition": "LIKE_NEW",
        "price": 120.00,
        "quantity": 1
    }
    
    # Call method
    result = await inventory_manager.create_inventory_item(1, item_data)
    
    # Verify result
    assert result is not None
    assert result.ebay_sku == "ebay-sku-new"
    assert result.condition == "LIKE_NEW"
    
    # Verify client was called with correct data
    mock_client.create_or_replace_inventory_item.assert_called_once()
    args, kwargs = mock_client.create_or_replace_inventory_item.call_args
    assert args[0] == "ebay-sku-new"  # SKU
    assert "price" in args[1]
    assert args[1]["price"]["value"] == "120.00"
    assert args[1]["availability"]["shipToLocationAvailability"]["quantity"] == 1
    
    # Verify database was updated
    assert platform_common.sync_status == SyncStatus.SYNCED.value
    assert platform_common.last_synced_at is not None

@pytest.mark.asyncio
async def test_create_inventory_item_platform_not_found(db_session, mocker):
    """Test create_inventory_item with non-existent platform_common"""
    # Mock db_session.execute to return None (not found)
    async def mock_execute(statement, *args, **kwargs):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        return mock_result
    
    mocker.patch.object(db_session, 'execute', side_effect=mock_execute)
    
    # Create inventory manager
    inventory_manager = EbayInventoryManager(db_session, MagicMock())
    
    # Call method and expect an exception
    with pytest.raises(ValueError) as exc_info:
        await inventory_manager.create_inventory_item(999, {})
    
    # Verify the error message
    assert "not found" in str(exc_info.value)

@pytest.mark.asyncio
async def test_create_inventory_item_api_error(db_session, mocker):
    """Test create_inventory_item handling API errors"""
    # Create test objects
    product = MagicMock()
    platform_common = MagicMock(
        id=1,
        product_id=1,
        platform_name="ebay",
        external_id=None,
        status=ListingStatus.DRAFT.value,
        sync_status=SyncStatus.PENDING.value,
        product=product
    )
    
    # Mock db_session.execute
    async def mock_execute(statement, *args, **kwargs):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = platform_common
        return mock_result
    
    mocker.patch.object(db_session, 'execute', side_effect=mock_execute)
    mocker.patch.object(db_session, 'add', MagicMock())
    mocker.patch.object(db_session, 'commit', AsyncMock())
    
    # Mock client to raise an API error
    mock_client = MagicMock(spec=EbayClient)
    mock_client.create_or_replace_inventory_item = AsyncMock(side_effect=EbayAPIError("API Error"))
    
    # Create inventory manager with mocked client
    inventory_manager = EbayInventoryManager(db_session, MagicMock())
    inventory_manager.client = mock_client
    
    # Call method and expect an exception
    with pytest.raises(EbayAPIError) as exc_info:
        await inventory_manager.create_inventory_item(1, {"sku": "test-sku"})
    
    # Verify the error message
    assert "API Error" in str(exc_info.value)
    
    # Verify sync status was updated to ERROR
    assert platform_common.sync_status == SyncStatus.ERROR.value
    assert platform_common.sync_message is not None
    assert "API Error" in platform_common.sync_message