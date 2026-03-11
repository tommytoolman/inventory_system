# tests/unit/woocommerce/test_errors.py
"""Unit tests for WooCommerce error hierarchy."""

import pytest

from app.services.woocommerce.errors import (
    WCAuthenticationError,
    WCConnectionError,
    WCRateLimitError,
    WCProductNotFoundError,
    WCValidationError,
    WCImageUploadError,
    WCWebhookError,
    WCAPIError,
    WCDataTransformError,
    WCSyncConflictError,
    WCOrderImportError,
    WCInventoryUpdateError,
)
from app.core.exceptions import WooCommerceAPIError, WooCommerceServiceError


class TestErrorHierarchy:
    """Test that all exception types inherit correctly."""

    def test_api_errors_inherit_woocommerce_api_error(self):
        api_errors = [
            WCAuthenticationError, WCConnectionError, WCRateLimitError,
            WCProductNotFoundError, WCValidationError, WCImageUploadError,
            WCWebhookError, WCAPIError,
        ]
        for cls in api_errors:
            err = cls("test error")
            assert isinstance(err, WooCommerceAPIError), f"{cls.__name__} should inherit from WooCommerceAPIError"

    def test_service_errors_inherit_woocommerce_service_error(self):
        service_errors = [
            WCDataTransformError, WCSyncConflictError,
            WCOrderImportError, WCInventoryUpdateError,
        ]
        for cls in service_errors:
            err = cls("test error")
            assert isinstance(err, WooCommerceServiceError), f"{cls.__name__} should inherit from WooCommerceServiceError"


class TestErrorSerialization:
    """Test to_dict() serialisation."""

    def test_to_dict_basic(self):
        err = WCAPIError(
            "Something went wrong",
            operation="import_product",
            wc_product_id="42",
            http_status=500,
        )
        d = err.to_dict()
        assert d["error_type"] == "WCAPIError"
        assert d["message"] == "Something went wrong"
        assert d["operation"] == "import_product"
        assert d["wc_product_id"] == "42"
        assert d["http_status"] == 500

    def test_to_dict_excludes_none(self):
        err = WCAPIError("test", operation="test_op")
        d = err.to_dict()
        assert "product_id" not in d  # None values excluded
        assert "http_status" not in d

    def test_to_dict_includes_response_body(self):
        err = WCAPIError(
            "test",
            response_body="a" * 3000,
        )
        d = err.to_dict()
        assert len(d["response_body"]) <= 2000

    def test_to_dict_includes_extra_fields(self):
        err = WCAPIError("test", custom_field="custom_value")
        d = err.to_dict()
        assert d["custom_field"] == "custom_value"


class TestRateLimitError:
    """Test WCRateLimitError has retry_after."""

    def test_has_retry_after(self):
        err = WCRateLimitError("Rate limited", retry_after=120)
        assert err.retry_after == 120

    def test_default_retry_after(self):
        err = WCRateLimitError("Rate limited")
        assert err.retry_after == 60


class TestErrorContext:
    """Test that error context attributes are set."""

    def test_all_context_attributes(self):
        err = WCAuthenticationError(
            "Auth failed",
            operation="api_products",
            product_id=1,
            wc_product_id="42",
            sku="RIFF-001",
            http_status=401,
            request_method="GET",
            request_url="https://store.example.com/wp-json/wc/v3/products",
            response_body="Unauthorized",
            retry_count=2,
        )
        assert err.operation == "api_products"
        assert err.product_id == 1
        assert err.wc_product_id == "42"
        assert err.sku == "RIFF-001"
        assert err.http_status == 401
        assert err.request_method == "GET"
        assert err.request_url == "https://store.example.com/wp-json/wc/v3/products"
        assert err.response_body == "Unauthorized"
        assert err.retry_count == 2


class TestErrorTrackerSummary:
    """Test error tracker summary grouping."""

    def test_summary_groups_by_type(self):
        from app.services.woocommerce.error_tracker import WCErrorTracker

        tracker = WCErrorTracker(sync_run_id="test-run")
        tracker.record(WCValidationError("Bad data 1"))
        tracker.record(WCValidationError("Bad data 2"))
        tracker.record(WCConnectionError("Timeout"))

        summary = tracker.get_summary()
        assert summary["total_errors"] == 3
        assert summary["by_type"]["WCValidationError"] == 2
        assert summary["by_type"]["WCConnectionError"] == 1

    def test_summary_detects_critical(self):
        from app.services.woocommerce.error_tracker import WCErrorTracker

        tracker = WCErrorTracker()
        tracker.record(WCAuthenticationError("Bad key"))
        assert tracker.has_critical_errors() is True

    def test_summary_no_critical(self):
        from app.services.woocommerce.error_tracker import WCErrorTracker

        tracker = WCErrorTracker()
        tracker.record(WCValidationError("Bad data"))
        assert tracker.has_critical_errors() is False

    def test_summary_sample_errors(self):
        from app.services.woocommerce.error_tracker import WCErrorTracker

        tracker = WCErrorTracker()
        tracker.record(WCValidationError("Error 1"))
        tracker.record(WCConnectionError("Error 2"))

        summary = tracker.get_summary()
        assert len(summary["sample_errors"]) == 2

    def test_summary_action_required(self):
        from app.services.woocommerce.error_tracker import WCErrorTracker

        tracker = WCErrorTracker()
        tracker.record(WCAuthenticationError("Bad key"))

        summary = tracker.get_summary()
        assert len(summary["action_required"]) > 0
        assert any("WC_CONSUMER_KEY" in a for a in summary["action_required"])
