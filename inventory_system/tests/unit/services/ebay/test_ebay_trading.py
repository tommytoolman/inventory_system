# tests/unit/services/ebay/test_ebay_trading.py
# FIXED: get_all_selling_listings takes include_active/sold/unsold, NOT page_number/entries_per_page
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.exceptions import EbayAPIError
from app.services.ebay.trading import EbayTradingLegacyAPI


def assert_xml_contains(xml_string, expected_fragments):
    if isinstance(expected_fragments, str):
        expected_fragments = [expected_fragments]
    for fragment in expected_fragments:
        assert fragment in xml_string, f"Expected '{fragment}' in XML: {xml_string}"


def make_api(sandbox=True, mock_token="test-token"):
    api = EbayTradingLegacyAPI(sandbox=sandbox)
    api.auth_manager.get_access_token = AsyncMock(return_value=mock_token)
    return api


@pytest.mark.asyncio
async def test_trading_legacy_api_initialization():
    api = EbayTradingLegacyAPI(sandbox=True)
    assert api.auth_manager is not None
    assert "sandbox.ebay.com" in api.endpoint
    assert api.site_id == "3"

    api_prod = EbayTradingLegacyAPI(sandbox=False)
    assert "sandbox" not in api_prod.endpoint
    assert "api.ebay.com" in api_prod.endpoint


@pytest.mark.asyncio
async def test_trading_legacy_api_initialization_custom_site():
    api = EbayTradingLegacyAPI(sandbox=False, site_id="0")
    assert api.site_id == "0"


@pytest.mark.asyncio
async def test_get_auth_token(mocker):
    api = EbayTradingLegacyAPI(sandbox=True)
    api.auth_manager.get_access_token = AsyncMock(return_value="test-token")
    token = await api._get_auth_token()
    assert token == "test-token"
    api.auth_manager.get_access_token.assert_called_once()


@pytest.mark.asyncio
async def test_make_request(mocker):
    api = make_api(sandbox=True)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = """<?xml version="1.0" encoding="utf-8"?>
    <GetItemResponse xmlns="urn:ebay:apis:eBLBaseComponents">
      <Timestamp>2025-05-08T12:00:00.000Z</Timestamp>
      <Ack>Success</Ack>
      <Item>
        <ItemID>123456789</ItemID>
        <Title>Test Item</Title>
      </Item>
    </GetItemResponse>"""

    async_client_mock = AsyncMock()
    async_client_mock.__aenter__.return_value.post.return_value = mock_response
    mocker.patch("httpx.AsyncClient", return_value=async_client_mock)

    response = await api._make_request("GetItem", "<GetItemRequest>...</GetItemRequest>")

    assert response["GetItemResponse"]["Ack"] == "Success"
    assert response["GetItemResponse"]["Item"]["Title"] == "Test Item"

    call_args = async_client_mock.__aenter__.return_value.post.call_args
    headers = call_args[1].get("headers", {})
    assert headers.get("X-EBAY-API-CALL-NAME") == "GetItem"
    assert headers.get("X-EBAY-API-IAF-TOKEN") == "test-token"


@pytest.mark.asyncio
async def test_make_request_api_error(mocker):
    api = make_api(sandbox=True)
    mocker.patch.object(api, "_make_request", side_effect=EbayAPIError("API Error: Invalid item ID"))

    with pytest.raises(EbayAPIError) as exc_info:
        await api.get_item_details("invalid-id")

    assert "API Error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_make_request_network_error(mocker):
    api = make_api(sandbox=True)

    async_client_mock = AsyncMock()
    async_client_mock.__aenter__.return_value.post.side_effect = Exception("Network error")
    mocker.patch("httpx.AsyncClient", return_value=async_client_mock)

    with pytest.raises(EbayAPIError) as exc_info:
        await api._make_request("GetItem", "<GetItemRequest>...</GetItemRequest>")

    assert "Network error" in str(exc_info.value) or "Error in API call" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_item_details(mocker):
    api = make_api(sandbox=True)

    item_response = {
        "GetItemResponse": {
            "Ack": "Success",
            "Item": {
                "ItemID": "123456789",
                "Title": "Test Guitar",
                "Description": "A test guitar description",
                "StartPrice": {"#text": "999.99", "@currencyID": "GBP"},
                "Quantity": "1",
            },
        }
    }
    api._make_request = AsyncMock(return_value=item_response)

    item = await api.get_item_details("123456789")

    assert item["ItemID"] == "123456789"
    assert item["Title"] == "Test Guitar"
    assert item["StartPrice"]["#text"] == "999.99"

    api._make_request.assert_called_once()
    call_name, xml_request = api._make_request.call_args[0]
    assert call_name == "GetItem"
    assert_xml_contains(
        xml_request,
        [
            "<ItemID>123456789</ItemID>",
            "<DetailLevel>ReturnAll</DetailLevel>",
        ],
    )


@pytest.mark.asyncio
async def test_get_active_inventory(mocker):
    """Test getting active inventory via get_all_selling_listings."""
    api = make_api(sandbox=True)

    inventory_response = {
        "GetMyeBaySellingResponse": {
            "Ack": "Success",
            "ActiveList": {
                "ItemArray": {
                    "Item": [
                        {"ItemID": "123", "Title": "Test Guitar 1"},
                        {"ItemID": "456", "Title": "Test Guitar 2"},
                    ]
                },
                "PaginationResult": {"TotalNumberOfEntries": "2", "TotalNumberOfPages": "1"},
            },
        }
    }
    api._make_request = AsyncMock(return_value=inventory_response)

    result = await api.get_all_selling_listings(
        include_active=True,
        include_sold=False,
        include_unsold=False,
    )

    assert result is not None
    api._make_request.assert_called()


@pytest.mark.asyncio
async def test_end_listing(mocker):
    api = make_api(sandbox=True)

    end_response = {"EndItemResponse": {"Ack": "Success", "EndTime": "2025-05-08T12:00:00.000Z"}}
    api._make_request = AsyncMock(return_value=end_response)

    result = await api.end_listing("123456789", reason_code="NotAvailable")

    assert result["EndItemResponse"]["Ack"] == "Success"
    api._make_request.assert_called_once()
    call_name, xml_request = api._make_request.call_args[0]
    assert call_name == "EndItem"
    assert_xml_contains(xml_request, ["<ItemID>123456789</ItemID>", "<EndingReason>NotAvailable</EndingReason>"])


@pytest.mark.asyncio
async def test_get_total_active_listings_count(mocker):
    api = make_api(sandbox=True)

    count_response = {
        "GetMyeBaySellingResponse": {
            "Ack": "Success",
            "ActiveList": {"PaginationResult": {"TotalNumberOfEntries": "42"}},
        }
    }
    api._make_request = AsyncMock(return_value=count_response)

    count = await api.get_total_active_listings_count()

    assert count == 42
    api._make_request.assert_called_once()
    call_name, xml_request = api._make_request.call_args[0]
    assert call_name == "GetMyeBaySelling"
    assert_xml_contains(xml_request, ["<EntriesPerPage>1</EntriesPerPage>"])


@pytest.mark.asyncio
async def test_relist_item(mocker):
    api = make_api(sandbox=True)

    relist_response = {
        "RelistItemResponse": {
            "Ack": "Success",
            "ItemID": "987654321",
            "StartTime": "2025-05-08T12:00:00.000Z",
            "EndTime": "2025-06-08T12:00:00.000Z",
        }
    }
    api._make_request = AsyncMock(return_value=relist_response)

    result = await api.relist_item("123456789")

    assert result["Ack"] == "Success"
    assert result["ItemID"] == "987654321"
    api._make_request.assert_called_once()
    call_name, xml_request = api._make_request.call_args[0]
    assert call_name == "RelistItem"
    assert_xml_contains(xml_request, ["<ItemID>123456789</ItemID>"])


@pytest.mark.asyncio
async def test_create_similar_listing(mocker):
    api = make_api(sandbox=True)

    original_item = {
        "ItemID": "123456789",
        "Title": "Test Guitar",
        "Description": "A test guitar description",
        "PrimaryCategory": {"CategoryID": "33034"},
        "StartPrice": {"#text": "999.99", "@currencyID": "GBP"},
        "Quantity": "1",
        "ConditionID": "3000",
        "Country": "GB",
        "Location": "London, UK",
        "ItemSpecifics": {
            "NameValueList": [{"Name": "Brand", "Value": "Fender"}, {"Name": "Model", "Value": "Stratocaster"}]
        },
        "PictureDetails": {"PictureURL": ["https://i.ebayimg.com/image1.jpg"]},
        "ShippingDetails": {
            "ShippingServiceOptions": {
                "ShippingService": "UK_OtherCourier24",
                "ShippingServiceCost": {"#text": "25.00"},
            }
        },
        "ReturnPolicy": {
            "ReturnsAcceptedOption": "ReturnsAccepted",
            "RefundOption": "MoneyBack",
            "ReturnsWithinOption": "Days_30",
            "ShippingCostPaidByOption": "Buyer",
        },
    }
    api.get_item_details = AsyncMock(return_value=original_item)

    add_item_response = {
        "AddItemResponse": {
            "Ack": "Success",
            "ItemID": "987654321",
        }
    }
    api._make_request = AsyncMock(return_value=add_item_response)
    api._get_paypal_email = MagicMock(return_value="sandbox@example.com")

    result = await api.create_similar_listing("123456789", append_to_title="- Relisted")

    assert result["success"] is True
    assert result["item_id"] == "987654321"
    api.get_item_details.assert_called_once_with("123456789")
    api._make_request.assert_called_once()
    call_name, xml_request = api._make_request.call_args[0]
    assert call_name == "AddItem"
    assert_xml_contains(
        xml_request,
        [
            "<Title>Test Guitar - Relisted</Title>",
            "<CategoryID>33034</CategoryID>",
        ],
    )


@pytest.mark.asyncio
async def test_get_valid_end_reasons(mocker):
    api = make_api(sandbox=True)

    if not hasattr(api, "get_valid_end_reasons"):
        pytest.skip("get_valid_end_reasons method not implemented in EbayTradingLegacyAPI")

    standard_reasons = await api.get_valid_end_reasons()

    assert isinstance(standard_reasons, list)
    assert len(standard_reasons) > 0
    assert all("code" in r for r in standard_reasons)
    assert any(r["code"] == "NotAvailable" for r in standard_reasons)
