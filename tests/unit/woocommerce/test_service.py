# tests/unit/woocommerce/test_service.py
"""Unit tests for WooCommerceService."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from .conftest import MOCK_WC_PRODUCT, MOCK_WC_ORDER


@pytest.fixture
def mock_db():
    """Mock async database session."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.delete = AsyncMock()
    return db


@pytest.fixture
def service(mock_db, mock_settings):
    """Create WooCommerceService with mocked dependencies."""
    with patch("app.services.woocommerce_service.WooCommerceClient") as MockClient:
        MockClient.return_value = AsyncMock()
        with patch("app.services.woocommerce_service.get_settings", return_value=mock_settings):
            from app.services.woocommerce_service import WooCommerceService
            svc = WooCommerceService(mock_db, mock_settings)
            return svc


class TestPublishProduct:
    """Test publish_product method."""

    @pytest.mark.asyncio
    async def test_duplicate_check_raises_error(self, service, mock_db):
        """WC-BUG-006: Publishing twice should raise WCValidationError."""
        # Simulate existing PlatformCommon
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = MagicMock()  # Existing record
        mock_db.execute = AsyncMock(return_value=mock_result)

        from app.services.woocommerce.errors import WCValidationError
        with pytest.raises(WCValidationError, match="already has a WooCommerce listing"):
            await service.publish_product(1)

    @pytest.mark.asyncio
    async def test_meta_key_is_riff_id(self, service, mock_db):
        """WC-BUG-010: Meta key should be _riff_id not _riff_product_id."""
        # First call: no existing PlatformCommon
        # Second call: product found
        mock_product = MagicMock()
        mock_product.id = 1
        mock_product.title = "Test Guitar"
        mock_product.brand = "Fender"
        mock_product.model = "Strat"
        mock_product.description = "A guitar"
        mock_product.sku = "TEST-001"
        mock_product.base_price = 999.99
        mock_product.quantity = 1
        mock_product.primary_image = None
        mock_product.additional_images = []
        mock_product.category = None

        call_count = 0
        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = None  # No existing listing
            else:
                result.scalar_one_or_none.return_value = mock_product
            return result

        mock_db.execute = mock_execute

        service.client.create_product = AsyncMock(return_value={
            "id": 42, "permalink": "https://example.com/p/42",
            "slug": "test", "name": "Test", "status": "publish",
            "type": "simple", "sku": "TEST-001", "price": "999.99",
            "regular_price": "999.99", "manage_stock": True,
            "stock_quantity": 1, "stock_status": "instock",
        })

        result = await service.publish_product(1)

        # Check that the payload sent to WC uses _riff_id
        call_args = service.client.create_product.call_args
        payload = call_args[0][0]
        meta_keys = [m["key"] for m in payload["meta_data"]]
        assert "_riff_id" in meta_keys
        assert "_riff_product_id" not in meta_keys
        assert "_riff_last_sync" in meta_keys

    @pytest.mark.asyncio
    async def test_meta_data_protected_from_extra_data(self, service, mock_db):
        """WC-BUG-015: extra_data should not overwrite meta_data."""
        mock_product = MagicMock()
        mock_product.id = 1
        mock_product.title = "Test"
        mock_product.brand = "Test"
        mock_product.model = "Test"
        mock_product.description = ""
        mock_product.sku = "TEST-001"
        mock_product.base_price = 100.0
        mock_product.quantity = 1
        mock_product.primary_image = None
        mock_product.additional_images = []
        mock_product.category = None

        call_count = 0
        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = None
            else:
                result.scalar_one_or_none.return_value = mock_product
            return result

        mock_db.execute = mock_execute

        service.client.create_product = AsyncMock(return_value={
            "id": 42, "permalink": "https://example.com/p/42",
            "slug": "test", "name": "Test", "status": "publish",
            "type": "simple", "sku": "TEST-001", "price": "100",
            "regular_price": "100", "manage_stock": True,
            "stock_quantity": 1, "stock_status": "instock",
        })

        extra = {"meta_data": [{"key": "custom_field", "value": "custom_value"}]}
        await service.publish_product(1, extra_data=extra)

        call_args = service.client.create_product.call_args
        payload = call_args[0][0]
        meta_keys = [m["key"] for m in payload["meta_data"]]
        # Both RIFF meta and custom meta should be present
        assert "_riff_id" in meta_keys
        assert "custom_field" in meta_keys


class TestOrderImport:
    """Test order import and product linking."""

    @pytest.mark.asyncio
    async def test_import_creates_orders(self, service, mock_db):
        """Orders should be created in the database."""
        service.client.get_all_orders = AsyncMock(return_value=[MOCK_WC_ORDER])

        # Mock: no existing order
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.import_orders()
        assert result["created"] == 1
        assert result["total"] == 1


class TestParseDateTime:
    """Test datetime parsing helper."""

    def test_parse_iso_datetime(self, service):
        dt = service._parse_datetime("2026-03-08T10:30:00")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 3

    def test_parse_none_returns_none(self, service):
        assert service._parse_datetime(None) is None

    def test_parse_invalid_returns_none(self, service):
        assert service._parse_datetime("not-a-date") is None
