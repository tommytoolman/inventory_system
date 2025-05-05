import pytest
from io import StringIO
import csv

# Import the service and models
from app.services.vintageandrare.export import VRExportService
from app.models.product import Product
from app.models.platform_common import PlatformCommon

# --- Fixtures ---

@pytest.fixture
def vr_export_service(db_session): # Use real test DB session
    return VRExportService(db_session=db_session)

@pytest.fixture
async def sample_products_for_export(db_session):
    """Create sample products in the test DB for export."""
    async with db_session.begin(): # Use transaction
        prod1 = Product(sku="EXP-001", brand="ExportBrand", model="ModelX", base_price=100.0, category="Cat1")
        prod2 = Product(sku="EXP-002", brand="ExportBrand", model="ModelY", base_price=200.0, category="Cat2", is_sold=True)
        prod3 = Product(sku="EXP-003", brand="AnotherBrand", model="ModelZ", base_price=300.0, category="Cat1")
        db_session.add_all([prod1, prod2, prod3])
        await db_session.flush() # Get IDs

        # Add a VR platform listing for one product
        pc1 = PlatformCommon(product_id=prod1.id, platform_name="vintageandrare", external_id="VR123")
        # Add a non-VR listing for another to test filtering/joining
        pc3 = PlatformCommon(product_id=prod3.id, platform_name="ebay", external_id="EBAY456")
        db_session.add_all([pc1, pc3])

    await db_session.commit() # Commit after setting up data
    # Return IDs or objects if needed by tests, though service queries directly
    return [prod1.id, prod2.id, prod3.id]


# --- Test Cases ---

@pytest.mark.asyncio
async def test_generate_csv_structure(vr_export_service, sample_products_for_export):
    """Test the generated CSV has the correct header and basic structure."""
    service = vr_export_service
    # sample_products_for_export fixture ensures data is in the DB

    csv_buffer: StringIO = await service.generate_csv()
    csv_content = csv_buffer.getvalue()

    # Check header
    assert csv_content.startswith(','.join(VRExportService.CSV_COLUMNS))

    # Check number of rows (header + products potentially linked to VR or without any listing)
    # The query joins isouter=True and filters for VR or None platform_name
    # Prod1 has VR listing, Prod2 has no listing, Prod3 has eBay listing.
    # So, Prod1 and Prod2 should appear.
    lines = csv_content.strip().split('\r\n') # V&R likely uses \r\n
    assert len(lines) == 3 # Header + Prod1 + Prod2

@pytest.mark.asyncio
async def test_generate_csv_content(vr_export_service, sample_products_for_export):
    """Test the content formatting for exported products."""
    service = vr_export_service

    csv_buffer: StringIO = await service.generate_csv()
    csv_reader = csv.DictReader(csv_buffer)
    rows = list(csv_reader)

    assert len(rows) == 2 # Prod1 and Prod2 expected

    # Check Row 1 (Product 1 - has VR listing)
    row1 = rows[0]
    assert row1['brand name'] == 'ExportBrand'
    assert row1['product model name'] == 'ModelX'
    assert row1['product price'] == '100' # Should be int stringified
    assert row1['product id'] == 'VR123' # External ID from PlatformCommon
    assert row1['product sold'] == 'no'
    assert row1['category name'] == 'Cat1'

    # Check Row 2 (Product 2 - no VR listing, is sold)
    row2 = rows[1]
    assert row2['brand name'] == 'ExportBrand'
    assert row2['product model name'] == 'ModelY'
    assert row2['product price'] == '200'
    assert row1['product id'] == '' # No external ID as no VR PlatformCommon
    assert row2['product sold'] == 'yes'
    assert row2['category name'] == 'Cat2'

# Add tests for formatting edge cases (missing data, price calculation logic if complex)