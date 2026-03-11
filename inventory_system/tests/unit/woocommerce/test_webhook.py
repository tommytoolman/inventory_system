# tests/unit/woocommerce/test_webhook.py
"""Unit tests for WooCommerce webhook endpoints."""

import base64
import hashlib
import hmac
import json
import pytest
from unittest.mock import patch, MagicMock

from .conftest import MOCK_WC_PRODUCT, MOCK_WC_ORDER


def _sign_payload(payload_bytes: bytes, secret: str) -> str:
    """Generate a valid WooCommerce webhook signature."""
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    ).decode("utf-8")


class TestWebhookSignatureVerification:
    """Test HMAC-SHA256 signature verification."""

    def test_valid_signature(self):
        from app.routes.platforms.woocommerce import verify_wc_webhook_signature

        payload = b'{"id": 42}'
        secret = "test_secret"
        signature = _sign_payload(payload, secret)

        assert verify_wc_webhook_signature(payload, signature, secret) is True

    def test_invalid_signature(self):
        from app.routes.platforms.woocommerce import verify_wc_webhook_signature

        payload = b'{"id": 42}'
        secret = "test_secret"

        assert verify_wc_webhook_signature(payload, "invalid_sig", secret) is False

    def test_empty_signature(self):
        from app.routes.platforms.woocommerce import verify_wc_webhook_signature

        payload = b'{"id": 42}'
        assert verify_wc_webhook_signature(payload, "", "secret") is False

    def test_empty_secret(self):
        from app.routes.platforms.woocommerce import verify_wc_webhook_signature

        payload = b'{"id": 42}'
        signature = _sign_payload(payload, "secret")
        assert verify_wc_webhook_signature(payload, signature, "") is False

    def test_tampered_payload(self):
        from app.routes.platforms.woocommerce import verify_wc_webhook_signature

        payload = b'{"id": 42}'
        secret = "test_secret"
        signature = _sign_payload(payload, secret)

        tampered = b'{"id": 43}'
        assert verify_wc_webhook_signature(tampered, signature, secret) is False


class TestDeliveryIdCache:
    """Test duplicate delivery ID rejection."""

    def test_first_delivery_not_seen(self):
        from app.routes.platforms.woocommerce import _DeliveryIdCache

        cache = _DeliveryIdCache()
        assert cache.seen("delivery-001") is False

    def test_duplicate_delivery_is_seen(self):
        from app.routes.platforms.woocommerce import _DeliveryIdCache

        cache = _DeliveryIdCache()
        cache.seen("delivery-001")
        assert cache.seen("delivery-001") is True

    def test_different_deliveries_not_seen(self):
        from app.routes.platforms.woocommerce import _DeliveryIdCache

        cache = _DeliveryIdCache()
        cache.seen("delivery-001")
        assert cache.seen("delivery-002") is False

    def test_max_size_evicts_oldest(self):
        from app.routes.platforms.woocommerce import _DeliveryIdCache

        cache = _DeliveryIdCache(max_size=3)
        cache.seen("d1")
        cache.seen("d2")
        cache.seen("d3")
        cache.seen("d4")  # Should evict d1
        # d1 should no longer be in cache
        assert cache.seen("d1") is False  # Re-adds it as new
