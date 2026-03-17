# tests/conftest.py
import asyncio  # noqa: F401
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.config import Settings
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

# Tenant Zero UUID constant (Hanks Music)
TENANT_ZERO_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture(scope="session")
def settings():
    """Provide test settings"""
    return Settings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        EBAY_API_KEY="test_key",
        REVERB_API_KEY="test_key",
        WEBHOOK_SECRET="test_secret",
    )


@pytest.fixture
def tenant_id():
    """Return the Tenant Zero UUID for use in test data."""
    return TENANT_ZERO_ID


@pytest.fixture
async def db_session():
    """
    Provide a mock AsyncSession for unit tests.

    Unit tests should not depend on a live database. This fixture provides a
    MagicMock that quacks like an AsyncSession so tests can verify DB
    interactions without needing PostgreSQL running locally.

    Tests that genuinely need DB integration should be marked @pytest.mark.integration
    and will be skipped by the default test runner.
    """
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.delete = MagicMock()
    # Default execute result: scalar returns None, all returns []
    mock_result = MagicMock()
    mock_result.scalar = MagicMock(return_value=None)
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    mock_result.all = MagicMock(return_value=[])
    mock_result.fetchall = MagicMock(return_value=[])
    mock_result.first = MagicMock(return_value=None)
    session.execute.return_value = mock_result
    yield session


@pytest.fixture
def test_client(settings):
    """Provide a test client with overridden settings"""

    def get_settings():
        return settings

    app.dependency_overrides[get_settings] = get_settings
    with TestClient(app) as client:
        yield client


# Mock fixtures for external services
# FIX: Use the actual import paths that exist in the codebase
@pytest.fixture
def mock_ebay_client(mocker):
    """Provide a mocked EbayClient — returns a plain MagicMock with update_quantity."""
    mock = MagicMock()
    mock.update_quantity = MagicMock()
    return mock


@pytest.fixture
def mock_reverb_client(mocker):
    """Provide a mocked ReverbClient — returns a plain MagicMock with update_quantity."""
    mock = MagicMock()
    mock.update_quantity = MagicMock()
    return mock


@pytest.fixture
def mock_shopify_client(mocker):
    """Provide a mocked ShopifyClient"""
    mock = MagicMock()
    return mock


@pytest.fixture
def mock_vintageandrare_client(mocker):
    """Provide a mocked VintageAndRareClient"""
    mock = MagicMock()
    return mock


@pytest.fixture
def sample_product_data():
    """Provide sample product data for tests"""
    return {
        "name": "Test Guitar",
        "sku": "TG-123",
        "price": 999.99,
        "condition": "excellent",
        "description": "A test guitar",
        "quantity": 1,
    }
