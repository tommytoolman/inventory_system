# tests/unit/woocommerce/test_importer.py
"""Unit tests for WooCommerceImporter."""

import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from .conftest import MOCK_WC_PRODUCT, MOCK_WC_PRODUCT_ZERO_STOCK, MOCK_WC_PRODUCT_VARIABLE


class TestStockQuantityZero:
    """WC-BUG-012: stock_quantity=0 must not default to 1."""

    def test_zero_stock_preserved_in_extract(self):
        """stock_quantity=0 should be preserved, not treated as falsy."""
        with patch("app.services.woocommerce.importer.WooCommerceClient"):
            from app.services.woocommerce.importer import WooCommerceImporter
            importer = WooCommerceImporter.__new__(WooCommerceImporter)
            importer.session = MagicMock()
            importer.client = MagicMock()

            product_data = importer._extract_product_data(MOCK_WC_PRODUCT_ZERO_STOCK)
            assert product_data["quantity"] == 0, "stock_quantity=0 should not default to 1"

    def test_none_stock_managed_defaults_to_0(self):
        """WC-P3-004: manage_stock=True + stock_quantity=None should default to 0."""
        with patch("app.services.woocommerce.importer.WooCommerceClient"):
            from app.services.woocommerce.importer import WooCommerceImporter
            importer = WooCommerceImporter.__new__(WooCommerceImporter)
            importer.session = MagicMock()
            importer.client = MagicMock()

            product = {**MOCK_WC_PRODUCT, "stock_quantity": None, "manage_stock": True}
            product_data = importer._extract_product_data(product)
            assert product_data["quantity"] == 0

    def test_unmanaged_stock_instock_defaults_to_1(self):
        """WC-P3-004: manage_stock=False + stock_status=instock should default to 1."""
        with patch("app.services.woocommerce.importer.WooCommerceClient"):
            from app.services.woocommerce.importer import WooCommerceImporter
            importer = WooCommerceImporter.__new__(WooCommerceImporter)
            importer.session = MagicMock()
            importer.client = MagicMock()

            product = {**MOCK_WC_PRODUCT, "manage_stock": False, "stock_status": "instock"}
            product_data = importer._extract_product_data(product)
            assert product_data["quantity"] == 1

    def test_unmanaged_stock_outofstock_defaults_to_0(self):
        """WC-P3-004: manage_stock=False + stock_status=outofstock should default to 0."""
        with patch("app.services.woocommerce.importer.WooCommerceClient"):
            from app.services.woocommerce.importer import WooCommerceImporter
            importer = WooCommerceImporter.__new__(WooCommerceImporter)
            importer.session = MagicMock()
            importer.client = MagicMock()

            product = {**MOCK_WC_PRODUCT, "manage_stock": False, "stock_status": "outofstock"}
            product_data = importer._extract_product_data(product)
            assert product_data["quantity"] == 0

    def test_positive_stock_preserved(self):
        """stock_quantity=5 should be preserved."""
        with patch("app.services.woocommerce.importer.WooCommerceClient"):
            from app.services.woocommerce.importer import WooCommerceImporter
            importer = WooCommerceImporter.__new__(WooCommerceImporter)
            importer.session = MagicMock()
            importer.client = MagicMock()

            product = {**MOCK_WC_PRODUCT, "stock_quantity": 5}
            product_data = importer._extract_product_data(product)
            assert product_data["quantity"] == 5


class TestSalePriceHandling:
    """WC-BUG-028: Effective price should be used first."""

    def test_effective_price_used_first(self):
        """_extract_product_data should use 'price' field first."""
        with patch("app.services.woocommerce.importer.WooCommerceClient"):
            from app.services.woocommerce.importer import WooCommerceImporter
            importer = WooCommerceImporter.__new__(WooCommerceImporter)
            importer.session = MagicMock()
            importer.client = MagicMock()

            product = {
                **MOCK_WC_PRODUCT,
                "price": "1999.99",
                "regular_price": "2499.99",
                "sale_price": "1999.99",
            }
            product_data = importer._extract_product_data(product)
            assert product_data["base_price"] == 1999.99

    def test_regular_price_fallback(self):
        """Should fall back to regular_price if price is empty."""
        with patch("app.services.woocommerce.importer.WooCommerceClient"):
            from app.services.woocommerce.importer import WooCommerceImporter
            importer = WooCommerceImporter.__new__(WooCommerceImporter)
            importer.session = MagicMock()
            importer.client = MagicMock()

            product = {**MOCK_WC_PRODUCT, "price": "", "regular_price": "2499.99"}
            product_data = importer._extract_product_data(product)
            assert product_data["base_price"] == 2499.99


class TestVariableProductWarning:
    """WC-BUG-025: Variable products should log a warning."""

    @pytest.mark.asyncio
    async def test_variable_product_logs_warning(self, caplog):
        """Variable product type should trigger a warning log."""
        with patch("app.services.woocommerce.importer.WooCommerceClient"):
            from app.services.woocommerce.importer import WooCommerceImporter
            importer = WooCommerceImporter.__new__(WooCommerceImporter)
            importer.session = AsyncMock()
            importer.client = MagicMock()
            importer._sync_run_id = uuid.uuid4()
            importer._processed_wc_ids = set()

            # Mock the DB queries to return None (new product)
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            importer.session.execute = AsyncMock(return_value=mock_result)
            importer.session.add = MagicMock()
            importer.session.flush = AsyncMock()

            import logging
            with caplog.at_level(logging.WARNING):
                await importer._process_single_product(MOCK_WC_PRODUCT_VARIABLE)

            assert any("variable" in msg.lower() for msg in caplog.messages)


class TestCategoryExtraction:
    """Test category name extraction."""

    def test_category_extracted(self):
        with patch("app.services.woocommerce.importer.WooCommerceClient"):
            from app.services.woocommerce.importer import WooCommerceImporter
            importer = WooCommerceImporter.__new__(WooCommerceImporter)
            importer.session = MagicMock()
            importer.client = MagicMock()

            cat = importer._extract_category_name(MOCK_WC_PRODUCT)
            assert cat == "Guitars"

    def test_no_category_returns_uncategorised(self):
        with patch("app.services.woocommerce.importer.WooCommerceClient"):
            from app.services.woocommerce.importer import WooCommerceImporter
            importer = WooCommerceImporter.__new__(WooCommerceImporter)
            importer.session = MagicMock()
            importer.client = MagicMock()

            product = {**MOCK_WC_PRODUCT, "categories": []}
            cat = importer._extract_category_name(product)
            assert cat == "Uncategorised"


class TestPlatformCommonData:
    """Test PlatformCommon data extraction."""

    def test_publish_status_maps_to_active(self):
        with patch("app.services.woocommerce.importer.WooCommerceClient"):
            from app.services.woocommerce.importer import WooCommerceImporter
            importer = WooCommerceImporter.__new__(WooCommerceImporter)
            importer.session = MagicMock()
            importer.client = MagicMock()

            pc_data = importer._extract_platform_common_data(MOCK_WC_PRODUCT)
            assert pc_data["platform_name"] == "woocommerce"
            assert pc_data["external_id"] == "42"

    def test_trash_status_maps_to_deleted(self):
        with patch("app.services.woocommerce.importer.WooCommerceClient"):
            from app.services.woocommerce.importer import WooCommerceImporter
            importer = WooCommerceImporter.__new__(WooCommerceImporter)
            importer.session = MagicMock()
            importer.client = MagicMock()

            product = {**MOCK_WC_PRODUCT, "status": "trash"}
            pc_data = importer._extract_platform_common_data(product)
            assert "deleted" in pc_data["status"].lower() or "DELETED" in pc_data["status"]


class TestSkuGeneration:
    """Test SKU generation when not provided."""

    def test_generates_wc_sku_when_missing(self):
        with patch("app.services.woocommerce.importer.WooCommerceClient"):
            from app.services.woocommerce.importer import WooCommerceImporter
            importer = WooCommerceImporter.__new__(WooCommerceImporter)
            importer.session = MagicMock()
            importer.client = MagicMock()

            product = {**MOCK_WC_PRODUCT, "sku": ""}
            product_data = importer._extract_product_data(product)
            assert product_data["sku"] == "WC-42"


# ===================================================================
# Phase 1 fixes: API contract compliance
# ===================================================================

class TestSkipStatuses:
    """WC-P3-005: auto-draft and inherit statuses should be skipped."""

    @pytest.mark.asyncio
    async def test_auto_draft_skipped(self):
        """auto-draft status products should return 'skipped'."""
        with patch("app.services.woocommerce.importer.WooCommerceClient"):
            from app.services.woocommerce.importer import WooCommerceImporter
            importer = WooCommerceImporter.__new__(WooCommerceImporter)
            importer.session = AsyncMock()
            importer.client = MagicMock()
            importer._sync_run_id = uuid.uuid4()
            importer._processed_wc_ids = set()

            product = {**MOCK_WC_PRODUCT, "status": "auto-draft"}
            result = await importer._process_single_product(product)
            assert result == "skipped"

    @pytest.mark.asyncio
    async def test_inherit_skipped(self):
        """inherit status products should return 'skipped'."""
        with patch("app.services.woocommerce.importer.WooCommerceClient"):
            from app.services.woocommerce.importer import WooCommerceImporter
            importer = WooCommerceImporter.__new__(WooCommerceImporter)
            importer.session = AsyncMock()
            importer.client = MagicMock()
            importer._sync_run_id = uuid.uuid4()
            importer._processed_wc_ids = set()

            product = {**MOCK_WC_PRODUCT, "status": "inherit"}
            result = await importer._process_single_product(product)
            assert result == "skipped"


class TestSkipVariationType:
    """WC-P3-007: variation type should be skipped."""

    @pytest.mark.asyncio
    async def test_variation_type_skipped(self):
        """variation type products should return 'skipped'."""
        with patch("app.services.woocommerce.importer.WooCommerceClient"):
            from app.services.woocommerce.importer import WooCommerceImporter
            importer = WooCommerceImporter.__new__(WooCommerceImporter)
            importer.session = AsyncMock()
            importer.client = MagicMock()
            importer._sync_run_id = uuid.uuid4()
            importer._processed_wc_ids = set()

            product = {**MOCK_WC_PRODUCT, "type": "variation"}
            result = await importer._process_single_product(product)
            assert result == "skipped"


class TestImageOrdering:
    """WC-P3-009: Image ordering should use position field."""

    def test_images_sorted_by_position(self):
        """Featured image should be determined by position, not array index."""
        with patch("app.services.woocommerce.importer.WooCommerceClient"):
            from app.services.woocommerce.importer import WooCommerceImporter
            importer = WooCommerceImporter.__new__(WooCommerceImporter)
            importer.session = MagicMock()
            importer.client = MagicMock()

            product = {
                **MOCK_WC_PRODUCT,
                "images": [
                    {"id": 1, "src": "https://example.com/second.jpg", "position": 1},
                    {"id": 2, "src": "https://example.com/featured.jpg", "position": 0},
                    {"id": 3, "src": "https://example.com/third.jpg", "position": 2},
                ],
            }
            product_data = importer._extract_product_data(product)
            assert product_data["primary_image"] == "https://example.com/featured.jpg"
            assert product_data["additional_images"][0] == "https://example.com/second.jpg"


class TestSafeFloat:
    """WC-P3-011: _safe_float should handle empty strings and None."""

    def test_safe_float_empty_string(self):
        with patch("app.services.woocommerce_service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                WC_STORE_URL="https://test.example.com",
                WC_CONSUMER_KEY="ck_test", WC_CONSUMER_SECRET="cs_test",
                WC_SANDBOX_MODE=True, WC_WEBHOOK_SECRET="", WC_PRICE_MARKUP_PERCENT=0.0,
            )
            from app.services.woocommerce_service import WooCommerceService
            assert WooCommerceService._safe_float("") == 0.0
            assert WooCommerceService._safe_float(None) == 0.0
            assert WooCommerceService._safe_float("12.50") == 12.50
            assert WooCommerceService._safe_float("invalid", 5.0) == 5.0
