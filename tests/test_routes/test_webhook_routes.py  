# tests/test_webhooks/test_webhook_processor.py
import pytest
import hmac
import hashlib
import json
from app.models.product import Product

# Handle WebhookProcessor import with fallback to mock
try:
    from app.services.webhook_processor import WebhookProcessor
except ImportError:
    # Create mock class if real one doesn't exist yet
    class WebhookProcessor:
        def __init__(self, session):
            self.session = session
        
        async def validate_signature(self, payload, signature):
            # Mock implementation
            return True
        
        async def process_order(self, webhook_data):
            # Mock implementation
            pass

@pytest.mark.asyncio
async def test_webhook_signature_validation(db_session, settings):
    """Test webhook signature validation"""
    processor = WebhookProcessor(db_session)
    payload = {"order_id": "123", "status": "completed"}
    
    # Generate valid signature
    message = json.dumps(payload).encode()
    signature = hmac.new(
        settings.WEBHOOK_SECRET.encode(),
        message,
        hashlib.sha256
    ).hexdigest()
    
    # Test valid signature
    assert await processor.validate_signature(payload, signature) is True
    
    # Test invalid signature
    assert await processor.validate_signature(payload, "invalid_signature") is False

@pytest.mark.asyncio
async def test_webhook_order_processing(
    db_session,
    mock_ebay_client,
    mock_reverb_client,
    sample_product_data
):
    """Test processing of webhook orders"""
    processor = WebhookProcessor(db_session)
    
    # Create test product
    product = Product(**sample_product_data)
    db_session.add(product)
    await db_session.commit()
    
    # Test order processing
    webhook_data = {
        "order_id": "123",
        "product_sku": sample_product_data["sku"],
        "quantity": 1
    }
    
    await processor.process_order(webhook_data)
    
    # Verify inventory was updated
    updated_product = await db_session.get(Product, product.id)
    assert updated_product.quantity == sample_product_data["quantity"] - 1
    
    # Verify platform updates were triggered
    mock_ebay_client.update_quantity.assert_called_once()
    mock_reverb_client.update_quantity.assert_called_once()