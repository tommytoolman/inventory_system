# tests/test_integrations/test_stock_manager.py
import pytest
from app.models.product import Product
from app.integrations.stock_manager import StockManager
from app.integrations.events import StockUpdateEvent

@pytest.mark.asyncio
async def test_stock_update_propagation(
    db_session,
    mock_ebay_client,
    mock_reverb_client,
    mock_vintageandrare_client,
    sample_product_data
):
    """Test stock updates are propagated to all platforms"""
    manager = StockManager(db_session)
    
    # Create test product
    product = Product(**sample_product_data)
    db_session.add(product)
    await db_session.commit()
    
    # Create stock update event
    event = StockUpdateEvent(
        product_id=product.id,
        new_quantity=0,
        platform="website"
    )
    
    # Process event
    await manager.handle_stock_update(event)
    
    # Verify all platforms were updated
    mock_ebay_client.update_quantity.assert_called_once_with(
        product.ebay_listing_id, 0
    )
    mock_reverb_client.update_quantity.assert_called_once_with(
        product.reverb_listing_id, 0
    )
    mock_vintageandrare_client.update_quantity.assert_called_once_with(
        product.vr_listing_id, 0
    )