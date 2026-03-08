# tests/unit/woocommerce/conftest.py
"""Shared fixtures for WooCommerce unit tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# -- Realistic music equipment test data --

MOCK_WC_PRODUCT = {
    "id": 42,
    "name": "Fender Stratocaster 1965 Vintage",
    "sku": "RIFF-STRAT-1965-001",
    "regular_price": "2499.99",
    "sale_price": "",
    "price": "2499.99",
    "stock_quantity": 1,
    "stock_status": "instock",
    "status": "publish",
    "type": "simple",
    "slug": "fender-stratocaster-1965-vintage",
    "permalink": "https://store.example.com/product/fender-stratocaster-1965-vintage",
    "description": "Beautiful vintage Fender Stratocaster in sunburst finish.",
    "short_description": "Classic 1965 Stratocaster",
    "manage_stock": True,
    "weight": "3.5",
    "shipping_class": "",
    "total_sales": 0,
    "date_created": "2026-01-15T10:30:00",
    "date_modified": "2026-03-01T14:00:00",
    "images": [{"id": 1, "src": "https://cdn.rifftechnology.com/images/strat-1965-front.jpg"}],
    "categories": [{"id": 12, "name": "Guitars", "slug": "guitars"}],
    "tags": [{"id": 34, "name": "Vintage", "slug": "vintage"}],
    "attributes": [
        {"name": "Brand", "options": ["Fender"]},
        {"name": "Model", "options": ["Stratocaster"]},
    ],
    "meta_data": [
        {"key": "_riff_id", "value": "riff-12345"},
        {"key": "_synced_from_riff", "value": "true"},
    ],
}

MOCK_WC_PRODUCT_ZERO_STOCK = {
    **MOCK_WC_PRODUCT,
    "id": 43,
    "stock_quantity": 0,
    "stock_status": "outofstock",
}

MOCK_WC_PRODUCT_VARIABLE = {
    **MOCK_WC_PRODUCT,
    "id": 44,
    "type": "variable",
    "name": "Gibson Les Paul Variable",
}

MOCK_WC_ORDER = {
    "id": 99,
    "number": "1099",
    "order_key": "wc_order_abc123",
    "status": "processing",
    "total": "2499.99",
    "subtotal": "2499.99",
    "shipping_total": "0.00",
    "total_tax": "0.00",
    "discount_total": "0.00",
    "currency": "GBP",
    "payment_method": "stripe",
    "payment_method_title": "Credit Card",
    "customer_id": 5,
    "billing": {
        "first_name": "John",
        "last_name": "Smith",
        "email": "john@example.com",
    },
    "shipping": {
        "first_name": "John",
        "last_name": "Smith",
        "address_1": "123 Music Lane",
        "address_2": "",
        "city": "London",
        "state": "",
        "postcode": "SW1A 1AA",
        "country": "GB",
    },
    "line_items": [
        {
            "product_id": 42,
            "sku": "RIFF-STRAT-1965-001",
            "quantity": 1,
            "total": "2499.99",
            "meta_data": [],
        }
    ],
    "date_created": "2026-03-08T10:30:00",
    "date_modified": "2026-03-08T10:35:00",
}

MOCK_WC_ORDER_COMPLETED = {
    **MOCK_WC_ORDER,
    "id": 100,
    "status": "completed",
}

MOCK_WC_ORDER_CANCELLED = {
    **MOCK_WC_ORDER,
    "id": 101,
    "status": "cancelled",
}


@pytest.fixture
def mock_wc_product():
    """A single WooCommerce product dict."""
    return MOCK_WC_PRODUCT.copy()


@pytest.fixture
def mock_wc_product_zero_stock():
    """A WooCommerce product with zero stock."""
    return MOCK_WC_PRODUCT_ZERO_STOCK.copy()


@pytest.fixture
def mock_wc_order():
    """A single WooCommerce order dict."""
    return MOCK_WC_ORDER.copy()


@pytest.fixture
def mock_settings():
    """Mock Settings object with WooCommerce configuration."""
    settings = MagicMock()
    settings.WC_STORE_URL = "https://store.example.com"
    settings.WC_CONSUMER_KEY = "ck_test_key"
    settings.WC_CONSUMER_SECRET = "cs_test_secret"
    settings.WC_AUTH_METHOD = "basic"
    settings.WC_SANDBOX_MODE = True
    settings.WC_PRICE_MARKUP_PERCENT = 0.0
    settings.WC_WEBHOOK_SECRET = "webhook_test_secret"
    settings.WEBHOOK_SECRET = "general_webhook_secret"
    settings.SECRET_KEY = "test_secret_key"
    return settings
