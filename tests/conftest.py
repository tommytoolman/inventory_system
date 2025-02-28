# tests/conftest.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import app
from app.core.config import Settings

# Test database URL
TEST_DATABASE_URL = "postgresql+asyncpg://test_user:test_pass@localhost/test_db"

@pytest.fixture(scope="session")
def settings():
    """Provide test settings"""
    return Settings(
        DATABASE_URL=TEST_DATABASE_URL,
        EBAY_API_KEY="test_key",
        REVERB_API_KEY="test_key",
        WEBHOOK_SECRET="test_secret",
    )

@pytest.fixture(scope="session")
async def test_engine():
    """Create and configure the test database engine"""
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()

@pytest.fixture
async def db_session(test_engine):
    """Provide a database session for tests"""
    async_session = sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session
        await session.rollback()

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
        "quantity": 1
    }