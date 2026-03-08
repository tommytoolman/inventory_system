# tests/unit/woocommerce/test_integration_seams.py
"""Tests for WooCommerce integration with shared RIFF services.

These tests verify that WooCommerce is correctly wired into:
- sync_all (multi-platform sync)
- EventProcessor (cross-platform event handling)
- OrderSaleProcessor (cross-platform order processing)
- Pricing service (markup calculation)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from .conftest import MOCK_WC_PRODUCT, MOCK_WC_ORDER


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def mock_db():
    """Mock async database session."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.delete = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.fixture
def mock_settings():
    """Mock Settings object with WooCommerce configuration."""
    settings = MagicMock()
    settings.WC_STORE_URL = "https://store.example.com"
    settings.WC_CONSUMER_KEY = "ck_test_key"
    settings.WC_CONSUMER_SECRET = "cs_test_secret"
    settings.WC_AUTH_METHOD = "basic"
    settings.WC_SANDBOX_MODE = True
    settings.WC_PRICE_MARKUP_PERCENT = 5.0
    settings.WC_WEBHOOK_SECRET = "webhook_test_secret"
    settings.WEBHOOK_SECRET = "general_webhook_secret"
    settings.SECRET_KEY = "test_secret_key"
    settings.EBAY_PRICE_MARKUP_PERCENT = 10.0
    settings.VR_PRICE_MARKUP_PERCENT = 8.0
    settings.REVERB_PRICE_MARKUP_PERCENT = 5.0
    settings.SHOPIFY_PRICE_MARKUP_PERCENT = 5.0
    return settings


# ===================================================================
# 1. sync_all calls WC background correctly (WC-P2-001)
# ===================================================================

class TestSyncAllSignature:
    """Verify run_woocommerce_sync_background accepts db parameter."""

    def test_sync_background_accepts_db_param(self):
        """WC-P2-001: run_woocommerce_sync_background must accept db kwarg."""
        import inspect
        from app.routes.platforms.woocommerce import run_woocommerce_sync_background
        sig = inspect.signature(run_woocommerce_sync_background)
        assert "db" in sig.parameters, "run_woocommerce_sync_background must accept 'db' parameter"

    def test_helper_function_exists(self):
        """WC-P2-001: _run_woocommerce_sync_with_session helper must exist."""
        from app.routes.platforms.woocommerce import _run_woocommerce_sync_with_session
        assert callable(_run_woocommerce_sync_with_session)


# ===================================================================
# 2-4. EventProcessor handles WC events (WC-P2-002)
# ===================================================================

class TestEventProcessorWooCommerce:
    """Verify EventProcessor imports and references WooCommerceService."""

    def test_event_processor_imports_woocommerce_service(self):
        """WC-P2-002: EventProcessor must import WooCommerceService."""
        from app.services import event_processor
        assert hasattr(event_processor, 'WooCommerceService')

    def test_price_change_is_not_stub(self):
        """WC-P2-002: _process_price_change should not be a stub any more."""
        import inspect
        from app.services.event_processor import _process_price_change
        source = inspect.getsource(_process_price_change)
        assert "not yet implemented" not in source, "_process_price_change is still a stub"


# ===================================================================
# 5. Order webhook processes single order (WC-P2-003)
# ===================================================================

class TestOrderWebhookSingleOrder:
    """Verify order webhook calls import_single_order, not import_orders."""

    def test_webhook_handler_uses_import_single_order(self):
        """WC-P2-003: _process_order_webhook_background must call import_single_order."""
        import inspect
        from app.routes.platforms.woocommerce import _process_order_webhook_background
        source = inspect.getsource(_process_order_webhook_background)
        assert "import_single_order" in source, "Order webhook should use import_single_order"
        assert "import_orders()" not in source, "Order webhook should NOT call import_orders()"

    def test_import_single_order_method_exists(self):
        """WC-P2-003: WooCommerceService must have import_single_order method."""
        from app.services.woocommerce_service import WooCommerceService
        assert hasattr(WooCommerceService, 'import_single_order')


# ===================================================================
# 6. OrderSaleProcessor updates WC listing (WC-P2-012)
# ===================================================================

class TestOrderSaleProcessorWC:
    """Verify OrderSaleProcessor handles woocommerce platform."""

    def test_update_source_platform_handles_woocommerce(self):
        """WC-P2-012: _update_source_platform_local_db must handle woocommerce."""
        import inspect
        from app.services.order_sale_processor import OrderSaleProcessor
        source = inspect.getsource(OrderSaleProcessor._update_source_platform_local_db)
        assert "woocommerce" in source, "Missing woocommerce case in _update_source_platform_local_db"
        assert "WooCommerceListing" in source

    def test_process_order_accepts_woocommerce_order(self):
        """WC-P2-013: process_order type hint must include WooCommerceOrder."""
        import inspect
        from app.services.order_sale_processor import OrderSaleProcessor
        source = inspect.getsource(OrderSaleProcessor.process_order)
        assert "WooCommerceOrder" in source

    def test_lazy_loader_exists(self):
        """WC-P2-014: _get_woocommerce_service() must exist."""
        from app.services.order_sale_processor import OrderSaleProcessor
        assert hasattr(OrderSaleProcessor, '_get_woocommerce_service')


# ===================================================================
# 7. Pricing includes WooCommerce (WC-P2-015)
# ===================================================================

class TestPricingIncludesWooCommerce:
    """Verify pricing module has woocommerce in markup map."""

    def test_pricing_markup_includes_woocommerce(self, mock_settings):
        """WC-P2-015: calculate_platform_price must work for 'woocommerce'."""
        with patch("app.services.pricing.get_settings", return_value=mock_settings):
            from app.services.pricing import calculate_platform_price
            price = calculate_platform_price("woocommerce", 1000.0)
            # With 5% markup, should be 1050.0
            assert price == 1050.0

    def test_pricing_markup_not_zero_by_default(self, mock_settings):
        """WC-P2-015: woocommerce should use its configured markup, not fall back to 0."""
        with patch("app.services.pricing.get_settings", return_value=mock_settings):
            from app.services.pricing import calculate_platform_price
            price = calculate_platform_price("woocommerce", 500.0)
            assert price > 500.0, "WooCommerce markup should not be zero"


# ===================================================================
# 8. Publish product cleans up on DB failure (WC-P2-009)
# ===================================================================

class TestPublishProductCleanup:
    """Verify orphaned WC product is deleted on DB failure."""

    def test_publish_has_cleanup_logic(self):
        """WC-P2-009: publish_product must have orphan cleanup logic."""
        import inspect
        from app.services.woocommerce_service import WooCommerceService
        source = inspect.getsource(WooCommerceService.publish_product)
        assert "delete_product" in source, "publish_product missing orphan cleanup"
        assert "db.rollback" in source or "db_err" in source


# ===================================================================
# 9. import_single_order method (WC-P2-003)
# ===================================================================

class TestImportSingleOrder:
    """Verify import_single_order processes a single order correctly."""

    @pytest.mark.asyncio
    async def test_import_single_order_creates_order(self, mock_db, mock_settings):
        """import_single_order should create a WooCommerceOrder from payload."""
        with patch("app.services.woocommerce_service.WooCommerceClient") as MockClient:
            MockClient.return_value = AsyncMock()
            with patch("app.services.woocommerce_service.get_settings", return_value=mock_settings):
                from app.services.woocommerce_service import WooCommerceService

                svc = WooCommerceService(mock_db, mock_settings)

                # Mock no existing order
                mock_result = MagicMock()
                mock_result.scalar_one_or_none.return_value = None
                mock_db.execute = AsyncMock(return_value=mock_result)

                result = await svc.import_single_order(MOCK_WC_ORDER)
                assert result["action"] == "created"
                assert result["order_id"] == "99"


# ===================================================================
# 10. Atomic stock decrement (WC-P2-011)
# ===================================================================

class TestAtomicStockDecrement:
    """Verify SQL-level atomic decrement is used."""

    def test_uses_greatest_sql(self):
        """WC-P2-011: _process_order_sale should use SQL GREATEST for decrement."""
        import inspect
        from app.services.woocommerce_service import WooCommerceService
        source = inspect.getsource(WooCommerceService._process_order_sale)
        assert "GREATEST" in source, "Should use SQL GREATEST for atomic decrement"
        assert "db.refresh" in source or "self.db.refresh" in source


# ===================================================================
# 11-12. Webhook payload validation (WC-P2-017)
# ===================================================================

class TestWebhookPayloadValidation:
    """Verify payload validation rejects invalid and accepts valid data."""

    def test_rejects_invalid_product_id(self):
        """Validation should reject non-integer product ID."""
        from app.routes.platforms.woocommerce import _validate_webhook_product_payload
        with pytest.raises(ValueError, match="Invalid product id"):
            _validate_webhook_product_payload({"id": "not-an-int"})

    def test_rejects_negative_product_id(self):
        """Validation should reject negative product ID."""
        from app.routes.platforms.woocommerce import _validate_webhook_product_payload
        with pytest.raises(ValueError, match="Invalid product id"):
            _validate_webhook_product_payload({"id": -1})

    def test_accepts_valid_product_payload(self):
        """Validation should pass through valid product data."""
        from app.routes.platforms.woocommerce import _validate_webhook_product_payload
        result = _validate_webhook_product_payload(MOCK_WC_PRODUCT)
        assert result["id"] == 42
        assert result["name"] == MOCK_WC_PRODUCT["name"]

    def test_truncates_long_description(self):
        """Validation should truncate descriptions over 500KB."""
        from app.routes.platforms.woocommerce import _validate_webhook_product_payload
        long_desc = "x" * 600_000
        payload = {**MOCK_WC_PRODUCT, "description": long_desc}
        result = _validate_webhook_product_payload(payload)
        assert len(result["description"]) == 500_000

    def test_limits_images_to_50(self):
        """Validation should limit images to 50."""
        from app.routes.platforms.woocommerce import _validate_webhook_product_payload
        images = [{"src": f"https://example.com/{i}.jpg"} for i in range(100)]
        payload = {**MOCK_WC_PRODUCT, "images": images}
        result = _validate_webhook_product_payload(payload)
        assert len(result["images"]) == 50

    def test_rejects_invalid_order_id(self):
        """Validation should reject non-integer order ID."""
        from app.routes.platforms.woocommerce import _validate_webhook_order_payload
        with pytest.raises(ValueError, match="Invalid order id"):
            _validate_webhook_order_payload({"id": "not-an-int"})

    def test_accepts_valid_order_payload(self):
        """Validation should pass through valid order data."""
        from app.routes.platforms.woocommerce import _validate_webhook_order_payload
        result = _validate_webhook_order_payload(MOCK_WC_ORDER)
        assert result["id"] == 99

    def test_negative_price_corrected(self):
        """Negative prices should be corrected to '0'."""
        from app.routes.platforms.woocommerce import _validate_webhook_product_payload
        payload = {**MOCK_WC_PRODUCT, "regular_price": "-50"}
        result = _validate_webhook_product_payload(payload)
        assert result["regular_price"] == "0"


# ===================================================================
# 13. Client closed after test_connection (WC-P2-004)
# ===================================================================

class TestClientClosedAfterTestConnection:
    """Verify test_connection uses context manager."""

    def test_test_connection_uses_context_manager(self):
        """WC-P2-004: test_woocommerce_connection should use async with."""
        import inspect
        from app.routes.platforms.woocommerce import test_woocommerce_connection
        source = inspect.getsource(test_woocommerce_connection)
        assert "async with WooCommerceClient()" in source


# ===================================================================
# 14. Empty price logs warning (WC-P2-018)
# ===================================================================

class TestEmptyPriceWarning:
    """Verify importer warns on empty price fields."""

    def test_extract_product_data_warns_on_empty_price(self):
        """WC-P2-018: _extract_product_data should handle empty price gracefully."""
        import inspect
        from app.services.woocommerce.importer import WooCommerceImporter
        source = inspect.getsource(WooCommerceImporter._extract_product_data)
        assert "no price set" in source or "has no price" in source


# ===================================================================
# Additional: Service close methods (WC-P2-005)
# ===================================================================

class TestServiceCloseMethod:
    """Verify WooCommerceService and WooCommerceImporter have close()."""

    def test_service_has_close(self):
        """WC-P2-005: WooCommerceService must have close() method."""
        from app.services.woocommerce_service import WooCommerceService
        assert hasattr(WooCommerceService, 'close')
        assert hasattr(WooCommerceService, '__aenter__')
        assert hasattr(WooCommerceService, '__aexit__')

    def test_importer_has_close(self):
        """WC-P2-005: WooCommerceImporter must have close() method."""
        from app.services.woocommerce.importer import WooCommerceImporter
        assert hasattr(WooCommerceImporter, 'close')
        assert hasattr(WooCommerceImporter, '__aenter__')
        assert hasattr(WooCommerceImporter, '__aexit__')


# ===================================================================
# Defensive int() conversion (WC-P2-019)
# ===================================================================

class TestDefensiveIntConversion:
    """Verify _safe_int_id protects against non-numeric IDs."""

    def test_safe_int_id_valid(self, mock_db, mock_settings):
        """Valid numeric strings should convert."""
        with patch("app.services.woocommerce_service.WooCommerceClient") as MockClient:
            MockClient.return_value = AsyncMock()
            with patch("app.services.woocommerce_service.get_settings", return_value=mock_settings):
                from app.services.woocommerce_service import WooCommerceService
                svc = WooCommerceService(mock_db, mock_settings)
                assert svc._safe_int_id("42") == 42
                assert svc._safe_int_id(42) == 42

    def test_safe_int_id_invalid(self, mock_db, mock_settings):
        """Non-numeric strings should raise WCValidationError."""
        with patch("app.services.woocommerce_service.WooCommerceClient") as MockClient:
            MockClient.return_value = AsyncMock()
            with patch("app.services.woocommerce_service.get_settings", return_value=mock_settings):
                from app.services.woocommerce_service import WooCommerceService
                from app.services.woocommerce.errors import WCValidationError
                svc = WooCommerceService(mock_db, mock_settings)
                with pytest.raises(WCValidationError, match="Non-numeric"):
                    svc._safe_int_id("abc")
