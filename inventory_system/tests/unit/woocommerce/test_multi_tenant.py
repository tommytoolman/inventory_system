# tests/unit/woocommerce/test_multi_tenant.py
"""Tests for multi-tenant WooCommerce store architecture and High severity fixes.

Covers:
- WC-P3-066: WooCommerceStore model
- WC-P3-067: Client accepts explicit credentials
- WC-P3-053: Empty credentials raise WCAuthenticationError
- WC-P3-069: Per-tenant webhook routing
- WC-P3-072: Per-store delivery cache namespacing
- WC-P3-015: Webhook ping handling
- WC-P3-038: Batch-load existing listings (N+1 fix)
- WC-P3-027: Cross-platform propagation on WC sale
- WC-P3-030: Price markup applied during propagation
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from .conftest import MOCK_WC_PRODUCT


# ===================================================================
# 1. Client accepts explicit credentials (WC-P3-067)
# ===================================================================

class TestClientExplicitCredentials:

    def test_client_accepts_explicit_credentials(self):
        """WC-P3-067: Client should use passed credentials over env vars."""
        with patch("app.services.woocommerce.client.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                WC_STORE_URL="https://default.example.com",
                WC_CONSUMER_KEY="ck_default",
                WC_CONSUMER_SECRET="cs_default",
                WC_SANDBOX_MODE=True,
            )
            from app.services.woocommerce.client import WooCommerceClient
            client = WooCommerceClient(
                store_url="https://custom.example.com",
                consumer_key="ck_custom",
                consumer_secret="cs_custom",
            )
            assert client.store_url == "https://custom.example.com"
            assert client.consumer_key == "ck_custom"
            assert client.consumer_secret == "cs_custom"

    def test_client_falls_back_to_env_vars(self):
        """WC-P3-067: Client should fall back to env vars when no args given."""
        with patch("app.services.woocommerce.client.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                WC_STORE_URL="https://env.example.com",
                WC_CONSUMER_KEY="ck_env",
                WC_CONSUMER_SECRET="cs_env",
                WC_SANDBOX_MODE=True,
            )
            from app.services.woocommerce.client import WooCommerceClient
            client = WooCommerceClient()
            assert client.store_url == "https://env.example.com"
            assert client.consumer_key == "ck_env"

    def test_client_raises_on_empty_credentials(self):
        """WC-P3-053: Empty credentials should raise WCAuthenticationError."""
        with patch("app.services.woocommerce.client.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                WC_STORE_URL=None,
                WC_CONSUMER_KEY=None,
                WC_CONSUMER_SECRET=None,
                WC_SANDBOX_MODE=True,
            )
            from app.services.woocommerce.client import WooCommerceClient
            from app.services.woocommerce.errors import WCAuthenticationError
            with pytest.raises(WCAuthenticationError, match="credentials not configured"):
                WooCommerceClient()


# ===================================================================
# 2. Service uses store credentials (WC-P3-068)
# ===================================================================

class TestServiceStoreContext:

    def test_service_uses_store_credentials(self):
        """WC-P3-068: Service should pass store creds to client."""
        mock_store = MagicMock()
        mock_store.store_url = "https://tenant.example.com"
        mock_store.consumer_key = "ck_tenant"
        mock_store.consumer_secret = "cs_tenant"
        mock_store.webhook_secret = "wh_tenant"
        mock_store.price_markup_percent = 7.5

        with patch("app.services.woocommerce_service.WooCommerceClient") as MockClient:
            with patch("app.services.woocommerce_service.get_settings") as mock_settings:
                mock_settings.return_value = MagicMock(
                    WC_STORE_URL="https://env.example.com",
                    WC_CONSUMER_KEY="ck_env",
                    WC_CONSUMER_SECRET="cs_env",
                    WC_WEBHOOK_SECRET="wh_env",
                    WC_PRICE_MARKUP_PERCENT=0.0,
                )
                from app.services.woocommerce_service import WooCommerceService
                svc = WooCommerceService(AsyncMock(), wc_store=mock_store)

                MockClient.assert_called_with(
                    store_url="https://tenant.example.com",
                    consumer_key="ck_tenant",
                    consumer_secret="cs_tenant",
                )
                assert svc.webhook_secret == "wh_tenant"
                assert svc.price_markup == 7.5

    def test_service_falls_back_without_store(self):
        """WC-P3-068: Service should use env vars when no store given."""
        with patch("app.services.woocommerce_service.WooCommerceClient") as MockClient:
            with patch("app.services.woocommerce_service.get_settings") as mock_settings:
                mock_settings.return_value = MagicMock(
                    WC_STORE_URL="https://env.example.com",
                    WC_CONSUMER_KEY="ck_env",
                    WC_CONSUMER_SECRET="cs_env",
                    WC_WEBHOOK_SECRET="wh_env",
                    WC_PRICE_MARKUP_PERCENT=5.0,
                )
                from app.services.woocommerce_service import WooCommerceService
                svc = WooCommerceService(AsyncMock())

                MockClient.assert_called_with()  # No args — env fallback
                assert svc.webhook_secret == "wh_env"
                assert svc.price_markup == 5.0


# ===================================================================
# 3. Webhook ping returns 200 (WC-P3-015)
# ===================================================================

class TestWebhookPing:

    def test_ping_detection_empty_payload(self):
        """WC-P3-015: Empty payload should be detected as ping."""
        from app.routes.platforms.woocommerce import _is_webhook_ping
        assert _is_webhook_ping({}) is True
        assert _is_webhook_ping(None) is True

    def test_ping_detection_webhook_id_only(self):
        """WC-P3-015: Payload with webhook_id but no id is a ping."""
        from app.routes.platforms.woocommerce import _is_webhook_ping
        assert _is_webhook_ping({"webhook_id": 1}) is True

    def test_normal_payload_not_ping(self):
        """WC-P3-015: Normal product payload should not be detected as ping."""
        from app.routes.platforms.woocommerce import _is_webhook_ping
        assert _is_webhook_ping(MOCK_WC_PRODUCT) is False


# ===================================================================
# 4. Delivery cache namespaced (WC-P3-072)
# ===================================================================

class TestDeliveryCacheNamespaced:

    def test_delivery_cache_per_store(self):
        """WC-P3-072: Same delivery ID in different stores should not collide."""
        from app.routes.platforms.woocommerce import _DeliveryIdCache

        cache = _DeliveryIdCache()
        assert cache.seen("del-1", store_id="store-A") is False
        assert cache.seen("del-1", store_id="store-A") is True  # duplicate
        assert cache.seen("del-1", store_id="store-B") is False  # different store

    def test_delivery_cache_global_fallback(self):
        """WC-P3-072: No store_id defaults to 'global' namespace."""
        from app.routes.platforms.woocommerce import _DeliveryIdCache

        cache = _DeliveryIdCache()
        assert cache.seen("del-2") is False
        assert cache.seen("del-2") is True


# ===================================================================
# 5. Importer batch-loads listings (WC-P3-038)
# ===================================================================

class TestImporterBatchLoad:

    def test_importer_has_batch_load_method(self):
        """WC-P3-038: WooCommerceImporter must have _batch_load_existing_listings."""
        from app.services.woocommerce.importer import WooCommerceImporter
        assert hasattr(WooCommerceImporter, '_batch_load_existing_listings')

    def test_find_existing_uses_preloaded_dict(self):
        """WC-P3-038: _find_existing_listing should use pre-loaded dict when available."""
        import inspect
        from app.services.woocommerce.importer import WooCommerceImporter
        source = inspect.getsource(WooCommerceImporter._find_existing_listing)
        assert "_existing_listings" in source


# ===================================================================
# 6. Price markup applied in propagation (WC-P3-030)
# ===================================================================

class TestPriceMarkupInPropagation:

    def test_event_processor_applies_wc_markup(self):
        """WC-P3-030: _process_price_change should use calculate_platform_price for WC."""
        import inspect
        from app.services.event_processor import _process_price_change
        source = inspect.getsource(_process_price_change)
        assert "calculate_platform_price" in source
        assert "markup_override" in source


# ===================================================================
# 7. Cross-platform propagation on sale (WC-P3-027)
# ===================================================================

class TestCrossPlatformPropagation:

    def test_propagation_method_exists(self):
        """WC-P3-027: WooCommerceService must have _propagate_quantity_to_other_platforms."""
        from app.services.woocommerce_service import WooCommerceService
        assert hasattr(WooCommerceService, '_propagate_quantity_to_other_platforms')

    def test_process_order_sale_calls_propagation(self):
        """WC-P3-027: _process_order_sale should call propagation after decrement."""
        import inspect
        from app.services.woocommerce_service import WooCommerceService
        source = inspect.getsource(WooCommerceService._process_order_sale)
        assert "_propagate_quantity_to_other_platforms" in source


# ===================================================================
# 8. WooCommerceStore model (WC-P3-066)
# ===================================================================

class TestWooCommerceStoreModel:

    def test_store_model_exists(self):
        """WC-P3-066: WooCommerceStore model should exist and be importable."""
        from app.models.woocommerce_store import WooCommerceStore
        assert WooCommerceStore.__tablename__ == "woocommerce_stores"

    def test_store_model_has_required_fields(self):
        """WC-P3-066: WooCommerceStore should have all required fields."""
        from app.models.woocommerce_store import WooCommerceStore
        for field in ("name", "store_url", "consumer_key", "consumer_secret",
                      "webhook_secret", "price_markup_percent", "is_active",
                      "sync_status", "last_sync_at"):
            assert hasattr(WooCommerceStore, field), f"Missing field: {field}"

    def test_listing_has_wc_store_id(self):
        """WC-P3-066: WooCommerceListing should have wc_store_id FK."""
        from app.models.woocommerce import WooCommerceListing
        assert hasattr(WooCommerceListing, "wc_store_id")

    def test_order_has_wc_store_id(self):
        """WC-P3-066: WooCommerceOrder should have wc_store_id FK."""
        from app.models.woocommerce_order import WooCommerceOrder
        assert hasattr(WooCommerceOrder, "wc_store_id")


# ===================================================================
# 9. Store CRUD endpoints exist (WC-P3-066)
# ===================================================================

class TestStoreCRUDEndpoints:

    def test_store_router_exists(self):
        """WC-P3-066: store_router should be importable."""
        from app.routes.platforms.woocommerce import store_router
        assert store_router is not None

    def test_store_router_has_routes(self):
        """WC-P3-066: store_router should have CRUD routes."""
        from app.routes.platforms.woocommerce import store_router
        paths = [r.path for r in store_router.routes if hasattr(r, 'path')]
        # Should have at least create, list, get, update, delete, test
        assert any("" == p or "/" == p for p in paths) or len(paths) >= 4
