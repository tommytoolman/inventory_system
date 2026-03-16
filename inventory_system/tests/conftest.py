# tests/conftest.py
import asyncio  # noqa: F401
import uuid

import pytest
from app.core.config import Settings
from app.database import Base
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Test database URL
TEST_DATABASE_URL = "postgresql+asyncpg://test_user:test_pass@localhost/test_db"

# Tenant Zero UUID constant (Hanks Music)
TENANT_ZERO_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture(scope="session")
def settings():
    """Provide test settings"""
    return Settings(
        DATABASE_URL=TEST_DATABASE_URL,
        EBAY_API_KEY="test_key",
        REVERB_API_KEY="test_key",
        WEBHOOK_SECRET="test_secret",
    )


# @pytest.mark.asyncio(scope="session")
# @pytest.fixture(scope="session")
# async def test_engine():
#     """Create and configure the test database engine (session-scoped loop).""" # Updated docstring
#     print("\nSetting up session-scoped test engine...") # Added print
#     engine = create_async_engine(TEST_DATABASE_URL)
#     async with engine.begin() as conn:
#         print("Dropping test DB tables...")
#         await conn.run_sync(Base.metadata.drop_all)
#         print("Creating test DB tables...")
#         await conn.run_sync(Base.metadata.create_all)
#         print("Test DB tables created.")
#     yield engine
#     print("\nDisposing session-scoped test engine...")
#     await engine.dispose()
#     print("Test engine disposed.")


# CHANGE SCOPE HERE from session to function
@pytest.fixture(scope="function")  # <--- Changed scope
async def test_engine():
    """Create and configure the test database engine (function-scoped)."""
    print("\nSetting up function-scoped test engine...")  # Optional: Update print statement
    engine = create_async_engine(TEST_DATABASE_URL)

    # Create tables for each test function
    async with engine.begin() as conn:
        print("Creating test DB tables...")
        await conn.run_sync(Base.metadata.create_all)
        # Seed Tenant Zero so FK constraints are satisfied
        await conn.execute(
            text(
                "INSERT INTO tenants (id, name, slug, status, created_at, updated_at) "
                "VALUES ('00000000-0000-0000-0000-000000000001', 'Test Tenant', 'test', 'active', "
                "timezone('utc', now()), timezone('utc', now())) "
                "ON CONFLICT DO NOTHING"
            )
        )
        print("Test DB tables created + Tenant Zero seeded.")

    yield engine  # Provide the engine to the test/fixtures

    # Dispose engine and drop tables after each test function
    print("\nDisposing function-scoped test engine...")  # Optional: Update print statement
    async with engine.begin() as conn:
        print("Dropping test DB tables post-test...")
        await conn.run_sync(Base.metadata.drop_all)  # Clean up after test
    await engine.dispose()
    print("Test engine disposed.")


@pytest.fixture
def tenant_id():
    """Return the Tenant Zero UUID for use in test data."""
    return TENANT_ZERO_ID


@pytest.fixture
async def db_session(test_engine):
    """Provide a database session for tests with tenant context set."""
    async_session_local = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session_local() as session:
        # Set tenant context for RLS (safe even if RLS not yet enabled)
        await session.execute(text(f"SET LOCAL app.current_tenant_id = '{TENANT_ZERO_ID}'"))
        yield session
        await session.rollback()
        print("DB session rolled back.")


@pytest.fixture
def test_client(settings):
    """Provide a test client with overridden settings"""

    def get_settings():
        return settings

    app.dependency_overrides[get_settings] = get_settings
    with TestClient(app) as client:
        yield client


# Mock fixtures for external services
@pytest.fixture
def mock_ebay_client(mocker):
    """Provide a mocked EbayClient"""
    return mocker.patch("app.integrations.platforms.ebay.EbayClient")


@pytest.fixture
def mock_reverb_client(mocker):
    """Provide a mocked ReverbClient"""
    return mocker.patch("app.integrations.platforms.reverb.ReverbClient")


@pytest.fixture
def mock_shopify_client(mocker):
    """Provide a mocked ShopifyClient"""
    return mocker.patch("app.integrations.platforms.shopify.ShopifyClient")


@pytest.fixture
def mock_vintageandrare_client(mocker):
    """Provide a mocked VintageAndRareClient"""
    return mocker.patch("app.integrations.platforms.vintageandrare.VintageAndRareClient")


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
