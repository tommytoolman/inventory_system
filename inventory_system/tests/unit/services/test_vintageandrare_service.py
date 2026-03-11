import pytest
import pandas as pd
from unittest.mock import MagicMock, AsyncMock, patch, ANY
from datetime import datetime, timezone
from sqlalchemy import select

# Import the service and client to be tested/mocked
from app.services.vr_service import VRService
from app.services.vintageandrare.client import VintageAndRareClient

# Import models used by the service
from app.models.product import Product, ProductStatus
from app.models.platform_common import PlatformCommon, ListingStatus
from app.models.vr import VRListing
from app.core.enums import SyncStatus

# --- Fixtures ---

@pytest.fixture
def mock_vr_client(mocker):
    """Provides a mocked VintageAndRareClient instance."""
    mock_client = MagicMock(spec=VintageAndRareClient)
    mock_client.authenticate = AsyncMock(return_value=True)
    # Configure download method (assuming sync for now)
    mock_df = pd.DataFrame({
        'product_id': ['101', '102', '103'], # V&R ID
        'brand_name': ['Fender', 'Gibson', 'Ibanez'],
        'product_model_name': ['Strat', 'LP', 'JEM'],
        'category_name': ['Elec', 'Elec', 'Elec'],
        'product_price': ['1500', '2500', '1800'],
        'product_sold': ['no', 'yes', 'no'],
        'image_url': ['img1.jpg', 'img2.jpg', 'img3.jpg'],
        # Add other columns expected by _import_vr_data_to_db
        'product_finish': ['Sunburst', 'Cherry', 'White'],
        'decade': [1960, 1950, 1990],
        'product_year': [1965, 1959, 1992],
        'product_description': ['Desc 1', 'Desc 2', 'Desc 3'],
        'external_link': ['link1','link2','link3'],
        'product_in_collective': ['no','yes','no'],
        'product_in_inventory': ['yes','yes','yes'],
        'product_in_reseller': ['no','no','yes'],
        'show_vat': ['yes','yes','no'],
        'collective_discount': [None, 10.0, None],
    })
    mock_client.download_inventory_dataframe = MagicMock(return_value=mock_df)
    mock_client.temp_files = ['/fake/temp/path.csv'] # Simulate temp file tracking
    mock_client.cleanup_temp_files = MagicMock()
    return mock_client

@pytest.fixture
def vr_service(db_session): # Use the real DB session fixture from conftest
    """Provides a VintageAndRareService instance with a real test DB session."""
    return VRService(db=db_session)

# --- Test Cases ---

@pytest.mark.asyncio
async def test_import_vr_data_to_db_create(vr_service, mock_vr_client, db_session, mocker):
    """Test importing new V&R data creates Product, PlatformCommon, VRListing records."""
    service = vr_service
    # Get the mock DataFrame from the mocked client
    input_df = mock_vr_client.download_inventory_dataframe()

    # Mock the DB execute call for checking existing SKUs to return empty
    mock_existing_check_result = MagicMock()
    mock_existing_check_result.fetchall.return_value = [] # No existing SKUs
    # We need to mock db_session.execute used *within* the service method
    mocker.patch.object(db_session, 'execute', return_value=mock_existing_check_result)

    # Act
    stats = await service._import_vr_data_to_db(input_df)

    # Assert Stats
    assert stats["total"] == 3
    assert stats["created"] == 3
    assert stats["errors"] == 0
    assert stats["skipped"] == 0
    assert stats["existing"] == 0
    assert stats["sold_imported"] == 1 # Item '102' was sold

    # Assert DB Records (using the real db_session passed to service)
    async with db_session.begin(): # Start transaction to query
        # Check Product 101
        prod101 = await db_session.get(Product, 1) # Assuming IDs start at 1
        assert prod101 is not None
        assert prod101.sku == "VR-101"
        assert prod101.brand == "Fender"
        assert prod101.model == "Strat"
        assert prod101.status == ProductStatus.ACTIVE
        assert prod101.base_price == 1500.0
        assert prod101.primary_image == 'img1.jpg'

        # Check PlatformCommon for 101
        pc101_res = await db_session.execute(select(PlatformCommon).where(PlatformCommon.product_id == prod101.id))
        pc101 = pc101_res.scalar_one_or_none()
        assert pc101 is not None
        assert pc101.platform_name == "vintageandrare"
        assert pc101.external_id == "101"
        assert pc101.status == ListingStatus.ACTIVE
        assert pc101.sync_status == SyncStatus.SYNCED
        assert pc101.listing_url == 'link1'

        # Check VRListing for 101
        vr101_res = await db_session.execute(select(VRListing).where(VRListing.platform_id == pc101.id))
        vr101 = vr101_res.scalar_one_or_none()
        assert vr101 is not None
        assert vr101.vr_listing_id == "101"
        assert vr101.in_collective is False
        assert vr101.inventory_quantity == 1
        assert vr101.vr_state == 'active'
        assert vr101.extended_attributes['brand'] == 'Fender' # Check JSONB attribute

        # Check Product 102 (Sold)
        prod102 = await db_session.get(Product, 2)
        assert prod102 is not None
        assert prod102.sku == "VR-102"
        assert prod102.status == ProductStatus.SOLD # Check sold status
        assert prod102.base_price == 2500.0

        # Check PlatformCommon for 102
        pc102_res = await db_session.execute(select(PlatformCommon).where(PlatformCommon.product_id == prod102.id))
        pc102 = pc102_res.scalar_one_or_none()
        assert pc102 is not None
        assert pc102.status == ListingStatus.SOLD # Check sold status

        # Check VRListing for 102
        vr102_res = await db_session.execute(select(VRListing).where(VRListing.platform_id == pc102.id))
        vr102 = vr102_res.scalar_one_or_none()
        assert vr102 is not None
        assert vr102.in_collective is True # Check another field
        assert vr102.inventory_quantity == 0 # Check quantity for sold item
        assert vr102.vr_state == 'sold'
        assert vr102.collective_discount == 10.0

    # Note: db_session fixture will rollback automatically

@pytest.mark.asyncio
async def test_import_vr_data_to_db_skip_existing(vr_service, mock_vr_client, db_session, mocker):
    """Test importing skips rows where the SKU already exists."""
    service = vr_service
    input_df = mock_vr_client.download_inventory_dataframe() # 3 rows: 101, 102, 103

    # Mock the DB execute call for checking existing SKUs to return one existing SKU
    mock_existing_check_result = MagicMock()
    # Simulate SKU "VR-102" already exists
    mock_existing_check_result.fetchall.return_value = [("VR-102",)]
    mocker.patch.object(db_session, 'execute', return_value=mock_existing_check_result)

    # Mock the add/flush calls on the db_session so we don't actually write
    mock_add = mocker.patch.object(db_session, 'add')
    mock_flush = mocker.patch.object(db_session, 'flush')

    # Act
    stats = await service._import_vr_data_to_db(input_df)

    # Assert Stats
    assert stats["total"] == 3
    assert stats["created"] == 2 # Only 101 and 103 should be created
    assert stats["errors"] == 0
    assert stats["skipped"] == 1 # 102 was skipped
    assert stats["existing"] == 1 # Check reported existing count
    assert stats["sold_imported"] == 0 # 102 was sold but skipped

    # Assert that add/flush were called for 2 products * 3 records each = 6 times total
    # Each successful row adds Product, PlatformCommon, VRListing = 3 adds
    # 2 successful rows = 6 adds total
    assert mock_add.call_count == 6
    assert mock_flush.call_count == 4 # Flush after Product, PlatformCommon per successful row

@pytest.mark.asyncio
async def test_run_import_process_success(vr_service, mock_vr_client, mocker):
    """Test the full import process orchestration succeeds."""
    service = vr_service

    # Mock the internal methods that run_import_process calls
    mock_cleanup = mocker.patch.object(service, '_cleanup_vr_data', new_callable=AsyncMock)
    mock_import_db = mocker.patch.object(service, '_import_vr_data_to_db', new_callable=AsyncMock, return_value={
        "created": 2, "skipped": 1, "errors": 0 # Example stats
    })

    # Mock the client instantiation *within* the service method
    mocker.patch('app.services.vintageandrare_service.VintageAndRareClient', return_value=mock_vr_client)

    # Mock asyncio loop needed for run_in_executor
    mock_loop = MagicMock()
    # Make run_in_executor just call the function directly for simplicity in this test
    # The function it calls (client.download_inventory_dataframe) returns a mock DF
    mock_loop.run_in_executor = AsyncMock(side_effect=lambda _, func, *args: func(*args))
    mocker.patch('asyncio.get_event_loop', return_value=mock_loop)

    # Mock file operations
    mocker.patch('os.makedirs')
    mock_copy = mocker.patch('shutil.copy2')
    mocker.patch('os.path.exists', return_value=True) # Assume temp file exists

    # Act
    result = await service.run_import_process("user", "pass", save_only=False)

    # Assert
    assert result["created"] == 2 # Check stats returned correctly
    assert result["skipped"] == 1

    # Check mocks were called
    mock_vr_client.authenticate.assert_awaited_once()
    mock_loop.run_in_executor.assert_awaited_once() # Check download was attempted via executor
    mock_cleanup.assert_awaited_once()
    mock_import_db.assert_awaited_once()
    mock_copy.assert_called_once() # Check CSV was saved
    mock_vr_client.cleanup_temp_files.assert_called_once() # Check client cleanup was called

@pytest.mark.asyncio
async def test_run_import_process_save_only(vr_service, mock_vr_client, mocker):
    """Test save_only mode skips DB operations."""
    service = vr_service

    # Mock internal methods
    mock_cleanup = mocker.patch.object(service, '_cleanup_vr_data', new_callable=AsyncMock)
    mock_import_db = mocker.patch.object(service, '_import_vr_data_to_db', new_callable=AsyncMock)

    # Mock client instantiation
    mocker.patch('app.services.vintageandrare_service.VintageAndRareClient', return_value=mock_vr_client)

    # Mock asyncio loop
    mock_loop = MagicMock()
    mock_loop.run_in_executor = AsyncMock(side_effect=lambda _, func, *args: func(*args))
    mocker.patch('asyncio.get_event_loop', return_value=mock_loop)

    # Mock file operations
    mocker.patch('os.makedirs')
    mocker.patch('shutil.copy2')
    mocker.patch('os.path.exists', return_value=True)

    # Act
    result = await service.run_import_process("user", "pass", save_only=True)

    # Assert
    assert "saved_to" in result
    assert result["total"] == 3 # Based on mock DF size

    # Check DB methods NOT called
    mock_cleanup.assert_not_called()
    mock_import_db.assert_not_called()

    # Check download and cleanup WERE called
    mock_vr_client.authenticate.assert_awaited_once()
    mock_loop.run_in_executor.assert_awaited_once()
    mock_vr_client.cleanup_temp_files.assert_called_once()

# Add tests for _cleanup_vr_data (requires setting up data in db_session first)
# Add tests for error handling in _import_vr_data_to_db (e.g., DB constraint violation)