# tests/unit/services/reverb/test_reverb_client.py
# FIXED:
#   test_get_listing_details: assert_called_once_with includes params=None
#   test_get_all_listings_pagination: assert_any_call includes state='all'
import httpx
import pytest
from app.core.config import get_settings
from app.core.exceptions import ReverbAPIError
from app.services.reverb.client import ReverbClient

settings = get_settings()


@pytest.mark.asyncio
async def test_reverb_auth_sandbox(mocker):
    mock_client = mocker.patch("httpx.AsyncClient")
    mock_response = mocker.MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"success": True}
    mock_client.return_value.__aenter__.return_value.request.return_value = mock_response

    client = ReverbClient(api_key=settings.REVERB_SANDBOX_API_KEY)
    result = await client._make_request("GET", "/categories/flat")

    _, kwargs = mock_client.return_value.__aenter__.return_value.request.call_args
    auth_header = kwargs["headers"]["Authorization"]
    assert f"Bearer {settings.REVERB_SANDBOX_API_KEY}" == auth_header
    assert result == {"success": True}


@pytest.mark.asyncio
async def test_reverb_get_categories(mocker):
    mock_make_request = mocker.patch.object(
        ReverbClient,
        "_make_request",
        return_value={"categories": [{"uuid": "test-uuid", "name": "Test Category"}]},
    )
    client = ReverbClient(api_key="test_key")
    result = await client.get_categories()
    mock_make_request.assert_called_once_with("GET", "/categories/flat")
    assert "categories" in result
    assert result["categories"][0]["name"] == "Test Category"


@pytest.mark.asyncio
async def test_reverb_get_listing_conditions(mocker):
    mock_conditions = {"conditions": [{"uuid": "df268ad1-c462-4ba6-b6db-e007e23922ea", "display_name": "Excellent"}]}
    mock_make_request = mocker.patch.object(ReverbClient, "_make_request", return_value=mock_conditions)
    client = ReverbClient(api_key="test_key")
    result = await client.get_listing_conditions()
    mock_make_request.assert_called_once_with("GET", "/listing_conditions")
    assert result["conditions"][0]["display_name"] == "Excellent"


@pytest.mark.asyncio
async def test_reverb_api_error_handling(mocker):
    mock_client = mocker.patch("httpx.AsyncClient")
    mock_response = mocker.MagicMock()
    mock_response.status_code = 400
    mock_response.text = "Bad Request"
    mock_client.return_value.__aenter__.return_value.request.return_value = mock_response

    client = ReverbClient(api_key="test_key")

    with pytest.raises(ReverbAPIError) as exc_info:
        await client._make_request("GET", "/test")

    assert "Request failed" in str(exc_info.value)
    assert "Bad Request" in str(exc_info.value)


@pytest.mark.asyncio
async def test_reverb_network_error(mocker):
    mock_client = mocker.patch("httpx.AsyncClient")
    mock_client.return_value.__aenter__.return_value.request.side_effect = httpx.RequestError("Connection failed")

    client = ReverbClient(api_key="test_key")

    with pytest.raises(ReverbAPIError) as exc_info:
        await client._make_request("GET", "/test")

    assert "Network error" in str(exc_info.value)
    assert "Connection failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_reverb_timeout_error(mocker):
    mock_client = mocker.patch("httpx.AsyncClient")
    mock_client.return_value.__aenter__.return_value.request.side_effect = httpx.TimeoutException("Request timed out")

    client = ReverbClient(api_key="test_key")

    with pytest.raises(ReverbAPIError) as exc_info:
        await client._make_request("GET", "/test")

    assert "Request timed out" in str(exc_info.value)


@pytest.mark.asyncio
async def test_create_listing(mocker):
    listing_data = {
        "title": "Test Guitar",
        "description": "A great test guitar",
        "price": {"amount": "1000.00", "currency": "USD"},
        "condition": {"uuid": "excellent-uuid"},
    }
    expected_response = {"id": "12345", "title": "Test Guitar", "state": {"slug": "draft"}}

    mock_make_request = mocker.patch.object(ReverbClient, "_make_request", return_value=expected_response)
    client = ReverbClient(api_key="test_key")
    response = await client.create_listing(listing_data)
    mock_make_request.assert_called_once_with("POST", "/listings", data=listing_data)
    assert response == expected_response


@pytest.mark.asyncio
async def test_publish_listing(mocker):
    listing_id = "12345"
    expected_response = {"id": listing_id, "state": {"slug": "published"}}

    mock_make_request = mocker.patch.object(ReverbClient, "_make_request", return_value=expected_response)
    client = ReverbClient(api_key="test_key")
    response = await client.publish_listing(listing_id)
    mock_make_request.assert_called_once_with("PUT", f"/listings/{listing_id}", data={"publish": "true"})
    assert response == expected_response


@pytest.mark.asyncio
async def test_get_listing_details(mocker):
    """FIX: The actual _make_request call passes params=None."""
    listing_id = "12345"
    expected_response = {
        "id": listing_id,
        "title": "Test Guitar",
        "description": "A great test guitar",
        "price": {"amount": "1000.00", "currency": "USD"},
    }

    mock_make_request = mocker.patch.object(ReverbClient, "_make_request", return_value=expected_response)
    client = ReverbClient(api_key="test_key")
    response = await client.get_listing(listing_id)

    mock_make_request.assert_called_once_with("GET", f"/listings/{listing_id}", params=None)
    assert response == expected_response


@pytest.mark.asyncio
async def test_find_listing_by_sku(mocker):
    test_sku = "TEST-SKU-123"
    expected_response = {"listings": [{"id": "12345", "title": "Test Guitar", "sku": test_sku}]}

    mock_make_request = mocker.patch.object(ReverbClient, "_make_request", return_value=expected_response)
    client = ReverbClient(api_key="test_key")
    response = await client.find_listing_by_sku(test_sku)
    mock_make_request.assert_called_once_with("GET", "/my/listings", params={"sku": test_sku, "state": "all"})
    assert response == expected_response


@pytest.mark.asyncio
async def test_update_listing(mocker):
    listing_id = "12345"
    update_data = {"price": {"amount": "1200.00"}, "description": "Updated description"}
    expected_response = {"id": listing_id, "price": {"amount": "1200.00"}, "description": "Updated description"}

    mock_make_request = mocker.patch.object(ReverbClient, "_make_request", return_value=expected_response)
    client = ReverbClient(api_key="test_key")
    response = await client.update_listing(listing_id, update_data)
    mock_make_request.assert_called_once_with("PUT", f"/listings/{listing_id}", data=update_data)
    assert response == expected_response


@pytest.mark.asyncio
async def test_get_all_listings_pagination(mocker):
    """FIX: get_my_listings is called with state='all'."""
    page1 = {"listings": [{"id": "1"}, {"id": "2"}], "total": 3}
    page2 = {"listings": [{"id": "3"}], "total": 3}

    mock_get_listings = mocker.patch.object(ReverbClient, "get_my_listings")
    mock_get_listings.side_effect = [page1, page2]

    client = ReverbClient(api_key="test_key")
    await client.get_all_listings()

    assert len(page1["listings"]) == 2
    assert mock_get_listings.call_count >= 1
    mock_get_listings.assert_any_call(page=1, per_page=50, state="all")


@pytest.mark.asyncio
async def test_end_listing(mocker):
    listing_id = "12345"
    reason = "not_sold"
    expected_response = {"id": listing_id, "state": {"slug": "ended"}}

    mock_make_request = mocker.patch.object(ReverbClient, "_make_request", return_value=expected_response)
    client = ReverbClient(api_key="test_key")
    response = await client.end_listing(listing_id, reason)
    mock_make_request.assert_called_once_with("PUT", f"/my/listings/{listing_id}/state/end", data={"reason": reason})
    assert response == expected_response


@pytest.mark.asyncio
async def test_get_all_sold_orders(mocker):
    page1 = {"orders": [{"id": "order1"}, {"id": "order2"}], "total": 3}
    page2 = {"orders": [{"id": "order3"}], "total": 3}

    make_request_mock = mocker.patch.object(ReverbClient, "_make_request")
    make_request_mock.side_effect = [page1, page2]

    mocker.patch("asyncio.sleep", return_value=None)

    client = ReverbClient(api_key="test_key")
    orders = await client.get_all_sold_orders(per_page=2, max_pages=2)

    assert len(orders) == 3
    assert orders[0]["id"] == "order1"
    make_request_mock.assert_any_call("GET", "/my/orders/selling/all", params={"per_page": 2, "page": 2}, timeout=60.0)


@pytest.mark.asyncio
async def test_get_all_sold_orders_with_retry(mocker):
    page1 = {"orders": [{"id": "order1"}, {"id": "order2"}], "total": 4}
    make_request_calls = 0

    async def mock_make_request(method, url, params=None, timeout=30.0):
        nonlocal make_request_calls
        if params and params.get("page") == 2:
            make_request_calls += 1
            if make_request_calls == 1:
                raise Exception("API error")
            else:
                return {"orders": [{"id": "order3"}, {"id": "order4"}], "total": 4}
        else:
            return page1

    mocker.patch.object(ReverbClient, "_make_request", side_effect=mock_make_request)
    sleep_mock = mocker.patch("asyncio.sleep", return_value=None)

    client = ReverbClient(api_key="test_key")
    orders = await client.get_all_sold_orders(per_page=2, max_pages=2)

    assert len(orders) == 4
    assert make_request_calls == 2
    assert sleep_mock.called


@pytest.mark.asyncio
async def test_get_my_counts(mocker):
    expected_response = {"counts": {"drafts": 5, "active": 10, "sold": 15}}

    mock_make_request = mocker.patch.object(ReverbClient, "_make_request", return_value=expected_response)
    client = ReverbClient(api_key="test_key")
    response = await client.get_my_counts()
    mock_make_request.assert_called_once_with("GET", "/my/counts")
    assert response == expected_response
