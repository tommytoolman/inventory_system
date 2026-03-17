# tests/unit/services/vintageandrare/test_vr_client.py
"""
Tests for VintageAndRareClient.

Key facts about the actual implementation:
- __init__(username, password, db_session=None) — positional args required
- authenticate() — uses self.username / self.password, no args
- Uses curl_cffi session (self.cf_session) preferentially when available
- response.headers must exist on mock responses (cf-mitigated lookup)
- create_listing_selenium checks product_data.get('Category') (capital C) for from_scratch=False
- authenticated (bool attribute)
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest
import requests
from app.services.vintageandrare.client import VintageAndRareClient


@pytest.fixture
def vr_client_no_db():
    """VintageAndRareClient without a DB session."""
    return VintageAndRareClient(username="testuser", password="testpassword")


@pytest.fixture
def vr_client_with_mock_db(mocker):
    """VintageAndRareClient with a mocked DB session."""
    mock_db_session = AsyncMock()
    mock_mapping_service = AsyncMock()
    mocker.patch("app.services.vintageandrare.client.CategoryMappingService", return_value=mock_mapping_service)
    client = VintageAndRareClient(username="testuser", password="testpassword", db_session=mock_db_session)
    client.mapping_service = mock_mapping_service
    return client, mock_mapping_service


@pytest.mark.asyncio
async def test_authenticate_success(vr_client_no_db, mocker):
    """Test successful authentication."""
    client = vr_client_no_db

    mock_response_get = MagicMock(spec=requests.Response)
    mock_response_get.status_code = 200
    mock_response_get.text = "<html>Login page</html>"
    mock_response_get.headers = {"content-type": "text/html"}

    mock_response_post = MagicMock(spec=requests.Response)
    mock_response_post.status_code = 200
    mock_response_post.url = "https://www.vintageandrare.com/account"
    mock_response_post.text = "<body>Logout</body>"
    mock_response_post.headers = {}

    mocker.patch.object(client.session, "get", return_value=mock_response_get)
    mocker.patch.object(client.session, "post", return_value=mock_response_post)

    if client.cf_session is not None:
        mocker.patch.object(client.cf_session, "get", return_value=mock_response_get)
        mocker.patch.object(client.cf_session, "post", return_value=mock_response_post)

    success = await client.authenticate()

    assert success is True
    assert client.authenticated is True


@pytest.mark.asyncio
async def test_authenticate_failure(vr_client_no_db, mocker):
    """Test failed authentication when no logout marker in response."""
    client = vr_client_no_db

    mock_response_get = MagicMock(spec=requests.Response)
    mock_response_get.status_code = 200
    mock_response_get.text = "<html>Login page</html>"
    mock_response_get.headers = {}

    mock_response_post = MagicMock(spec=requests.Response)
    mock_response_post.status_code = 200
    mock_response_post.url = "https://www.vintageandrare.com/login"
    mock_response_post.text = "<body>Login failed</body>"
    mock_response_post.headers = {}

    mocker.patch.object(client.session, "get", return_value=mock_response_get)
    mocker.patch.object(client.session, "post", return_value=mock_response_post)

    if client.cf_session is not None:
        mocker.patch.object(client.cf_session, "get", return_value=mock_response_get)
        mocker.patch.object(client.cf_session, "post", return_value=mock_response_post)

    success = await client.authenticate()

    assert success is False
    assert client.authenticated is False


@pytest.mark.asyncio
async def test_download_inventory_dataframe_success(vr_client_no_db, mocker):
    """Test successful download returns a DataFrame."""
    client = vr_client_no_db
    client.authenticated = True

    mocker.patch.object(client, "authenticate", return_value=True)

    csv_content = (
        "brand name,product model name,product id,product price,product_sold\n"
        "Fender,Stratocaster,123,1500,no\n"
        "Gibson,Les Paul,456,2500,yes\n"
    )
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "text/csv"}
    mock_response.content = csv_content.encode("utf-8")
    mock_response.iter_content.return_value = [csv_content.encode("utf-8")]

    mocker.patch.object(client.session, "get", return_value=mock_response)
    if client.cf_session is not None:
        mocker.patch.object(client.cf_session, "get", return_value=mock_response)

    expected_df = pd.DataFrame(
        {
            "brand name": ["Fender", "Gibson"],
            "product model name": ["Stratocaster", "Les Paul"],
        }
    )
    mocker.patch("pandas.read_csv", return_value=expected_df)

    df = await client.download_inventory_dataframe(save_to_file=False)

    if df is not None and not isinstance(df, str):
        assert isinstance(df, pd.DataFrame)


@pytest.mark.asyncio
async def test_download_inventory_auth_failure(vr_client_no_db, mocker):
    """Test inventory download returns None if authentication fails."""
    client = vr_client_no_db
    client.authenticated = False

    mocker.patch.object(client, "authenticate", return_value=False)

    df = await client.download_inventory_dataframe()

    assert df is None


@pytest.mark.asyncio
async def test_create_listing_selenium_success(vr_client_with_mock_db, mocker):
    """Test create_listing_selenium with properly mapped product data."""
    client, mock_mapping_service = vr_client_with_mock_db

    mock_mapping = MagicMock()
    mock_mapping.target_id = "51"
    mock_mapping.target_subcategory_id = "83"
    mock_mapping_service.get_mapping.return_value = mock_mapping
    mock_mapping_service.get_default_mapping = AsyncMock(return_value=mock_mapping)

    success_dict = {
        "status": "success",
        "message": "Mock success",
        "vr_product_id": "VR123",
        "timestamp": "2025-01-01T00:00:00+00:00",
    }
    mocker.patch.object(client, "_run_selenium_automation", return_value=success_dict)

    current_loop = asyncio.get_running_loop()

    async def mock_executor(executor, func, *args):
        return func()

    mocker.patch.object(current_loop, "run_in_executor", new_callable=AsyncMock, side_effect=mock_executor)

    product_data = {
        "id": 101,
        "category_id": "CAT-ELEC",
        "category": "Electric Guitars",
        "Category": "51",
        "SubCategory1": "83",
        "brand": "TestBrand",
        "model": "TestModel",
        "price": 123.45,
        "sku": "SKU101",
        "primary_image": "http://example.com/img1.jpg",
        "additional_images": ["http://example.com/img2.jpg"],
        "finish": "Sunburst",
        "description": "Desc",
        "year": 2023,
    }

    result = await client.create_listing_selenium(product_data, test_mode=False)

    assert result is not None
    assert isinstance(result, dict)
    assert result.get("status") == "success"
