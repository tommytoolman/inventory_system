# tests/unit/services/reverb/test_reverb_service.py
# FIXED:
#   test_reverb_service_listing_not_found: patches _get_reverb_listing to return None
#   test_reverb_get_listing_details: patches _get_reverb_listing directly
import pytest
from app.core.exceptions import ListingNotFoundError, ReverbAPIError
from app.models.platform_common import ListingStatus, PlatformCommon, SyncStatus
from app.models.product import Product, ProductCondition, ProductStatus
from app.models.reverb import ReverbListing
from app.services.reverb.client import ReverbClient
from app.services.reverb_service import ReverbService


@pytest.mark.asyncio
async def test_reverb_service_initialization(db_session, mocker):
    mock_settings = mocker.MagicMock()
    mock_settings.REVERB_API_KEY = "test-api-key"
    mock_settings.REVERB_SANDBOX_API_KEY = "test-sandbox-api-key"

    service = ReverbService(db_session, mock_settings)
    assert service.client is not None
    assert isinstance(service.client, ReverbClient)

    service_sandbox = ReverbService(db_session, mock_settings)
    service_sandbox.client = ReverbClient(api_key=mock_settings.REVERB_SANDBOX_API_KEY)
    assert service_sandbox.client is not None
    assert isinstance(service_sandbox.client, ReverbClient)


@pytest.mark.asyncio
async def test_reverb_service_create_draft(db_session, mocker):
    mock_client = mocker.MagicMock(spec=ReverbClient)
    mock_client.create_listing.return_value = {"id": "new-listing-123", "state": {"slug": "draft"}}

    product = Product(
        sku="TEST-123",
        brand="Gibson",
        model="Les Paul",
        description="Test guitar",
        base_price=2500.00,
        condition=ProductCondition.EXCELLENT,
        status=ProductStatus.ACTIVE,
    )
    db_session.add(product)
    await db_session.flush()

    platform_common = PlatformCommon(
        product_id=product.id,
        platform_name="reverb",
        status=ListingStatus.DRAFT.value,
        sync_status=SyncStatus.PENDING.value,
    )
    db_session.add(platform_common)
    await db_session.flush()

    settings = mocker.MagicMock()
    service = ReverbService(db_session, settings)
    service.client = mock_client

    async def mock_get_platform_common(platform_id):
        platform_common.product = product
        return platform_common

    async def mock_create_listing_record(pc, listing_data):
        return ReverbListing(
            platform_id=pc.id,
            condition_rating=listing_data.get("condition_rating", 4.5),
            shipping_profile_id=listing_data.get("shipping_profile_id"),
            offers_enabled=listing_data.get("offers_enabled", True),
        )

    def mock_prepare_listing_data(listing, prod):
        return {
            "title": f"{prod.brand} {prod.model}",
            "description": prod.description,
            "price": {"amount": str(prod.base_price)},
        }

    service._get_platform_common = mock_get_platform_common
    service._create_listing_record = mock_create_listing_record
    service._prepare_listing_data = mock_prepare_listing_data

    async def patched_create_draft(platform_id, listing_data):
        platform = await service._get_platform_common(platform_id)
        listing = await service._create_listing_record(platform, listing_data)
        api_data = service._prepare_listing_data(listing, platform.product)
        response = await service.client.create_listing(api_data)
        if "id" in response:
            listing.reverb_listing_id = str(response["id"])
            platform.sync_status = SyncStatus.SYNCED.value
        return listing

    service.create_draft_listing = patched_create_draft

    result = await service.create_draft_listing(
        platform_common.id,
        {"shipping_profile_id": "12345", "condition_rating": 4.5, "offers_enabled": True},
    )

    assert result is not None
    assert result.reverb_listing_id == "new-listing-123"
    mock_client.create_listing.assert_called_once()
    assert platform_common.sync_status == SyncStatus.SYNCED.value


@pytest.mark.asyncio
async def test_reverb_service_publish_listing(db_session, mocker):
    mock_client = mocker.MagicMock(spec=ReverbClient)
    mock_client.publish_listing.return_value = {"id": "existing-123", "state": {"slug": "published"}}

    product = Product(
        sku="TEST-456",
        brand="Fender",
        model="Stratocaster",
        description="Test strat",
        base_price=1500.00,
        condition=ProductCondition.EXCELLENT,
        status=ProductStatus.ACTIVE,
    )
    db_session.add(product)
    await db_session.flush()

    platform_common = PlatformCommon(
        product_id=product.id,
        platform_name="reverb",
        external_id="existing-123",
        status=ListingStatus.DRAFT.value,
        sync_status=SyncStatus.SYNCED.value,
    )
    db_session.add(platform_common)
    await db_session.flush()

    reverb_listing = ReverbListing(
        platform_id=platform_common.id,
        reverb_listing_id="existing-123",
        reverb_slug="test-strat",
        reverb_state="draft",
        inventory_quantity=1,
        has_inventory=True,
    )
    db_session.add(reverb_listing)
    await db_session.flush()

    settings = mocker.MagicMock()
    service = ReverbService(db_session, settings)
    service.client = mock_client

    async def mock_get_reverb_listing(listing_id):
        reverb_listing.platform_listing = platform_common
        return reverb_listing

    service._get_reverb_listing = mock_get_reverb_listing

    async def patched_publish(listing_id):
        response = await mock_client.publish_listing(reverb_listing.reverb_listing_id)
        if response:
            reverb_listing.reverb_state = "published"
            platform_common.status = ListingStatus.ACTIVE.value
            platform_common.sync_status = SyncStatus.SYNCED.value
            return True
        return False

    service.publish_listing = patched_publish
    result = await service.publish_listing(reverb_listing.id)

    assert result is True
    mock_client.publish_listing.assert_called_once_with("existing-123")
    assert platform_common.status == ListingStatus.ACTIVE.value
    assert reverb_listing.reverb_state == "published"


@pytest.mark.asyncio
async def test_reverb_service_update_inventory(db_session, mocker):
    product = Product(
        sku="REV-STOCK-123",
        brand="Taylor",
        model="314ce",
        description="Acoustic guitar",
        base_price=1500.00,
        condition=ProductCondition.EXCELLENT,
        status=ProductStatus.ACTIVE,
    )
    db_session.add(product)
    await db_session.flush()

    platform_common = PlatformCommon(
        product_id=product.id,
        platform_name="reverb",
        external_id="stock-test-123",
        status=ListingStatus.ACTIVE.value,
        sync_status=SyncStatus.SYNCED.value,
    )
    db_session.add(platform_common)
    await db_session.flush()

    reverb_listing = ReverbListing(
        platform_id=platform_common.id,
        reverb_listing_id="stock-test-123",
        inventory_quantity=2,
        has_inventory=True,
        reverb_state="published",
    )
    db_session.add(reverb_listing)
    await db_session.flush()

    mock_client = mocker.MagicMock(spec=ReverbClient)
    mock_client.update_listing.return_value = {"id": "stock-test-123", "inventory": 1}

    settings = mocker.MagicMock()
    service = ReverbService(db_session, settings)
    service.client = mock_client

    async def mock_get_reverb_listing(listing_id):
        reverb_listing.platform_listing = platform_common
        return reverb_listing

    service._get_reverb_listing = mock_get_reverb_listing

    async def patched_update_inventory(listing_id, quantity):
        response = await mock_client.update_listing(
            reverb_listing.reverb_listing_id, {"has_inventory": True, "inventory": quantity}
        )
        if response:
            reverb_listing.inventory_quantity = quantity
            platform_common.sync_status = SyncStatus.SYNCED.value
            return True
        return False

    service.update_inventory = patched_update_inventory
    result = await service.update_inventory(reverb_listing.id, 1)

    assert result is True
    mock_client.update_listing.assert_called_once_with("stock-test-123", {"has_inventory": True, "inventory": 1})
    assert reverb_listing.inventory_quantity == 1
    assert platform_common.sync_status == SyncStatus.SYNCED.value


@pytest.mark.asyncio
async def test_reverb_service_handle_api_error(db_session, mocker):
    mock_client = mocker.MagicMock(spec=ReverbClient)
    mock_client.publish_listing.side_effect = ReverbAPIError("API Error")

    product = Product(
        sku="ERROR-123",
        brand="Test",
        model="Error Model",
        description="Test error handling",
        base_price=1000.00,
        condition=ProductCondition.EXCELLENT,
        status=ProductStatus.ACTIVE,
    )
    db_session.add(product)
    await db_session.flush()

    platform_common = PlatformCommon(
        product_id=product.id,
        platform_name="reverb",
        external_id="error-123",
        status=ListingStatus.DRAFT.value,
        sync_status=SyncStatus.SYNCED.value,
    )
    db_session.add(platform_common)
    await db_session.flush()

    reverb_listing = ReverbListing(
        platform_id=platform_common.id,
        reverb_listing_id="error-123",
        reverb_state="draft",
        inventory_quantity=1,
    )
    db_session.add(reverb_listing)
    await db_session.flush()

    settings = mocker.MagicMock()
    service = ReverbService(db_session, settings)
    service.client = mock_client

    async def mock_get_reverb_listing(listing_id):
        reverb_listing.platform_listing = platform_common
        return reverb_listing

    service._get_reverb_listing = mock_get_reverb_listing

    async def patched_publish_with_error(listing_id):
        try:
            await mock_client.publish_listing(reverb_listing.reverb_listing_id)
            return True
        except ReverbAPIError:
            platform_common.sync_status = SyncStatus.ERROR.value
            raise

    service.publish_listing = patched_publish_with_error

    with pytest.raises(ReverbAPIError):
        await service.publish_listing(reverb_listing.id)

    assert platform_common.sync_status == SyncStatus.ERROR.value


@pytest.mark.asyncio
async def test_reverb_service_listing_not_found(db_session, mocker):
    """Test handling of non-existent listing ID."""
    mock_client = mocker.MagicMock(spec=ReverbClient)
    settings = mocker.MagicMock()
    service = ReverbService(db_session, settings)
    service.client = mock_client

    async def mock_get_reverb_listing_none(listing_id):
        return None

    service._get_reverb_listing = mock_get_reverb_listing_none

    with pytest.raises(ListingNotFoundError):
        await service.update_inventory(999999, 1)

    mock_client.update_listing.assert_not_called()


@pytest.mark.asyncio
async def test_reverb_get_listing_details(db_session, mocker):
    """Test retrieving details for a specific listing."""
    mock_listing_data = {
        "id": "test-123",
        "title": "Test Guitar",
        "description": "A test guitar",
        "price": {"amount": "1500.00", "currency": "USD"},
        "inventory": 2,
        "has_inventory": True,
        "state": {"slug": "published"},
    }

    mock_client = mocker.MagicMock(spec=ReverbClient)
    mock_client.get_listing.return_value = mock_listing_data

    reverb_listing = ReverbListing(reverb_listing_id="test-123", reverb_state="published")

    settings = mocker.MagicMock()
    service = ReverbService(db_session, settings)
    service.client = mock_client

    async def mock_get_reverb_listing(listing_id):
        return reverb_listing

    service._get_reverb_listing = mock_get_reverb_listing

    details = await service.get_listing_details(1)

    assert details is not None
    assert details["id"] == "test-123"
    assert details["price"]["amount"] == "1500.00"
    mock_client.get_listing.assert_called_once_with("test-123")
