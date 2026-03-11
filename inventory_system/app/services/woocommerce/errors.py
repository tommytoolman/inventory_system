# app/services/woocommerce/errors.py
"""
WooCommerce Error Hierarchy

Granular exception classes for the WooCommerce integration. Every exception
carries structured context (operation, product IDs, HTTP details) so error
logs are immediately actionable.

Hierarchy
---------
WooCommerceServiceError  (existing, in app.core.exceptions)
|-- WooCommerceAPIError  (existing)
|   |-- WCAuthenticationError    401/403, bad API keys
|   |-- WCConnectionError        Timeouts, DNS, store unreachable
|   |-- WCRateLimitError         429 rate limiting
|   |-- WCProductNotFoundError   404 on product endpoints
|   |-- WCValidationError        400/422 invalid data sent to API
|   |-- WCImageUploadError       Image URL failures
|   |-- WCWebhookError           Webhook delivery failures
|   +-- WCAPIError               Generic API error (catch-all)
|
|-- WCDataTransformError         Local data parsing failures
|-- WCSyncConflictError          Stale data / version mismatch
|-- WCOrderImportError           Order import failures
+-- WCInventoryUpdateError       Stock update failures

All exceptions are caught by existing ``except WooCommerceAPIError`` or
``except WooCommerceServiceError`` clauses -- no breaking changes.
"""

from app.core.exceptions import WooCommerceServiceError, WooCommerceAPIError


# ===================================================================
# Base mixin -- adds structured context to every WC exception
# ===================================================================

class WCErrorMixin:
    """
    Mixin that gives every WC exception a structured context dict.

    Attributes set automatically from __init__ kwargs:
        operation        -- what was being done  (import_product, publish, etc.)
        product_id       -- local RIFF product ID
        wc_product_id    -- WooCommerce product ID
        sku              -- product SKU
        http_status      -- HTTP response code
        request_method   -- GET / POST / PUT / DELETE
        request_url      -- full request URL
        response_body    -- truncated API response text
        retry_count      -- how many retries were attempted
    """

    def __init__(self, message: str, *, operation: str = None,
                 product_id: int = None, wc_product_id: str = None,
                 sku: str = None, http_status: int = None,
                 request_method: str = None, request_url: str = None,
                 response_body: str = None, retry_count: int = 0,
                 **extra):
        super().__init__(message)
        self.operation = operation
        self.product_id = product_id
        self.wc_product_id = wc_product_id
        self.sku = sku
        self.http_status = http_status
        self.request_method = request_method
        self.request_url = request_url
        self.response_body = response_body
        self.retry_count = retry_count
        self.extra = extra

    def to_dict(self) -> dict:
        """Serialise error context for logging / tracking."""
        d = {
            "error_type": type(self).__name__,
            "message": str(self),
            "operation": self.operation,
            "product_id": self.product_id,
            "wc_product_id": self.wc_product_id,
            "sku": self.sku,
            "http_status": self.http_status,
            "request_method": self.request_method,
            "request_url": self.request_url,
            "retry_count": self.retry_count,
        }
        if self.response_body:
            d["response_body"] = self.response_body[:2000]
        if self.extra:
            d.update(self.extra)
        return {k: v for k, v in d.items() if v is not None}


# ===================================================================
# API-level errors  (inherit from WooCommerceAPIError)
# Caught by:  except WooCommerceAPIError
# ===================================================================

class WCAuthenticationError(WCErrorMixin, WooCommerceAPIError):
    """401/403 -- Bad API keys, expired credentials, insufficient permissions."""
    pass


class WCConnectionError(WCErrorMixin, WooCommerceAPIError):
    """Timeouts, DNS failures, store URL unreachable."""
    pass


class WCRateLimitError(WCErrorMixin, WooCommerceAPIError):
    """429 -- Rate limited by WooCommerce."""

    def __init__(self, message: str, *, retry_after: int = 60, **kwargs):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class WCProductNotFoundError(WCErrorMixin, WooCommerceAPIError):
    """404 -- Product does not exist on WooCommerce."""
    pass


class WCValidationError(WCErrorMixin, WooCommerceAPIError):
    """400/422 -- Invalid data sent to WooCommerce API."""
    pass


class WCImageUploadError(WCErrorMixin, WooCommerceAPIError):
    """Image URL rejected, inaccessible, or failed to process."""
    pass


class WCWebhookError(WCErrorMixin, WooCommerceAPIError):
    """Webhook creation or delivery failure."""
    pass


class WCAPIError(WCErrorMixin, WooCommerceAPIError):
    """Generic API error with structured context (catch-all for unclassified HTTP errors)."""
    pass


# ===================================================================
# Service-level errors  (inherit from WooCommerceServiceError)
# Caught by:  except WooCommerceServiceError
# ===================================================================

class WCDataTransformError(WCErrorMixin, WooCommerceServiceError):
    """Local data extraction or parsing failure (not an API call issue)."""
    pass


class WCSyncConflictError(WCErrorMixin, WooCommerceServiceError):
    """Stale data, concurrent modification, or version mismatch during sync."""
    pass


class WCOrderImportError(WCErrorMixin, WooCommerceServiceError):
    """Order-specific import failure."""
    pass


class WCInventoryUpdateError(WCErrorMixin, WooCommerceServiceError):
    """Stock quantity update failure."""
    pass
