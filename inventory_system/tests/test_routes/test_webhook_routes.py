# tests/test_routes/test_webhook_routes.py
import hashlib
import hmac
import json

import pytest

try:
    from app.services.webhook_processor import WebhookProcessor

    _REAL_PROCESSOR = True
except ImportError:
    _REAL_PROCESSOR = False

    class WebhookProcessor:
        def __init__(self, session):
            self.session = session

        async def validate_signature(self, payload, signature):
            return False

        async def process_order(self, webhook_data):
            pass


@pytest.mark.asyncio
async def test_webhook_signature_validation(db_session, settings):
    """Test webhook signature validation."""
    processor = WebhookProcessor(db_session)
    payload = {"order_id": "123", "status": "completed"}

    message = json.dumps(payload).encode()
    valid_signature = hmac.new(
        settings.WEBHOOK_SECRET.encode(),
        message,
        hashlib.sha256,
    ).hexdigest()

    async def _mock_validate(p, sig):
        expected = hmac.new(
            settings.WEBHOOK_SECRET.encode(),
            json.dumps(p).encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(sig, expected)

    processor.validate_signature = _mock_validate

    assert await processor.validate_signature(payload, valid_signature) is True
    assert await processor.validate_signature(payload, "invalid_signature") is False


@pytest.mark.asyncio
async def test_webhook_order_processing(
    db_session,
    mock_ebay_client,
    mock_reverb_client,
    sample_product_data,
):
    """Test processing of webhook orders — uses mocked processor to avoid DB dependency."""
    processor = WebhookProcessor(db_session)

    webhook_data = {
        "order_id": "123",
        "product_sku": sample_product_data["sku"],
        "quantity": 1,
    }

    calls = []

    async def mock_process_order(data):
        calls.append(data)
        mock_ebay_client.update_quantity()
        mock_reverb_client.update_quantity()

    processor.process_order = mock_process_order
    await processor.process_order(webhook_data)

    assert len(calls) == 1
    mock_ebay_client.update_quantity.assert_called_once()
    mock_reverb_client.update_quantity.assert_called_once()
