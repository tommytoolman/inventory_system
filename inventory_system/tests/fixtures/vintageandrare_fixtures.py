import pytest
import pandas as pd
from unittest.mock import MagicMock

from app.services.vintageandrare.client import VintageAndRareClient
from app.models.vr import VRListing
from app.models.platform_common import PlatformCommon
from app.models.product import Product
from app.core.enums import ProductStatus, ProductCondition, ListingStatus, SyncStatus


@pytest.fixture
async def vr_test_product(db_session):
    """Create a test product linked to a V&R listing"""
    product = Product(
        sku="VR-FIXTURE-TEST",
        brand="Test Brand", 
        model="Test Model",
        category="Guitars",
        description="Test product from fixture",
        base_price=1000.00,
        condition=ProductCondition.EXCELLENT,
        status=ProductStatus.ACTIVE
    )
    db_session.add(product)
    await db_session.flush()
    
    platform_record = PlatformCommon(
        product_id=product.id,
        platform_name="vintageandrare",
        external_id="FIXTURE-TEST",
        status=ListingStatus.ACTIVE.value,
        sync_status=SyncStatus.SYNCED.value
    )
    db_session.add(platform_record)
    await db_session.flush()
    
    vr_listing = VRListing(
        platform_id=platform_record.id,
        vr_listing_id="FIXTURE-TEST",
        inventory_quantity=1,
        vr_state="active",
        price=1000.00
    )
    db_session.add(vr_listing)
    await db_session.flush()
    
    return {
        'product': product,
        'platform_record': platform_record,
        'vr_listing': vr_listing
    }


@pytest.fixture
def mock_vr_client():
    """Create a mock VintageAndRareClient"""
    mock_client = MagicMock(spec=VintageAndRareClient)
    mock_client.authenticate.return_value = True
    
    # Default test data
    test_data = [{
        "product_id": "TEST-123", 
        "brand_name": "Test Brand",
        "product_model_name": "Test Model",
        "category_name": "Guitars>Electric solid body",
        "product_price": "1000.00",
        "product_description": "Test product description",
        "product_sold": "no",
        "image_url": "https://example.com/image.jpg",
        "inventory_quantity": "1",
        "vr_listing_id": "TEST-123"
    }]
    
    mock_client.download_inventory_dataframe.return_value = pd.DataFrame(test_data)
    mock_client.temp_files = []
    
    return mock_client

