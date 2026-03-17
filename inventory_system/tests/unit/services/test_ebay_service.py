# tests/unit/services/test_ebay_service.py
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services.ebay.trading import EbayTradingLegacyAPI
from app.services.ebay_service import EbayService


@pytest.mark.asyncio
async def test_ebay_service_initialization(db_session, mocker):
    mock_settings = MagicMock()
    mock_settings.EBAY_SANDBOX_MODE = False

    service = EbayService(db_session, mock_settings)

    assert service.db == db_session
    assert service.settings == mock_settings
    assert service.trading_api is not None
    assert isinstance(service.trading_api, EbayTradingLegacyAPI)
    assert service.expected_user_id == "londonvintagegts"


@pytest.mark.asyncio
async def test_ebay_service_sandbox_mode(db_session, mocker):
    mock_settings = MagicMock()
    mock_settings.EBAY_SANDBOX_MODE = True

    service = EbayService(db_session, mock_settings)

    assert service.trading_api is not None
    assert service.trading_api.sandbox is True


@pytest.mark.asyncio
async def test_verify_credentials_success(db_session, mocker):
    mock_settings = MagicMock()
    mock_settings.EBAY_SANDBOX_MODE = False

    service = EbayService(db_session, mock_settings)
    service.expected_user_id = "londonvintagegts"
    service.trading_api.get_user_info = AsyncMock(
        return_value={"success": True, "user_data": {"UserID": "londonvintagegts"}}
    )

    result = await service.verify_credentials()
    assert result is True
    service.trading_api.get_user_info.assert_called_once()


@pytest.mark.asyncio
async def test_verify_credentials_wrong_user(db_session, mocker):
    mock_settings = MagicMock()
    mock_settings.EBAY_SANDBOX_MODE = False

    service = EbayService(db_session, mock_settings)
    service.expected_user_id = "londonvintagegts"
    service.trading_api.get_user_info = AsyncMock(return_value={"success": True, "user_data": {"UserID": "wrong_user"}})

    result = await service.verify_credentials()
    assert result is False


@pytest.mark.asyncio
async def test_verify_credentials_api_error(db_session, mocker):
    mock_settings = MagicMock()
    mock_settings.EBAY_SANDBOX_MODE = False

    service = EbayService(db_session, mock_settings)
    service.trading_api.get_user_info = AsyncMock(return_value={"success": False, "message": "API Error"})

    result = await service.verify_credentials()
    assert result is False


@pytest.mark.asyncio
async def test_load_category_map_returns_dict(db_session, mocker):
    mock_settings = MagicMock()
    mock_settings.EBAY_SANDBOX_MODE = False

    service = EbayService(db_session, mock_settings)
    assert isinstance(service.category_map, dict)
    assert len(service.category_map) > 0


@pytest.mark.asyncio
async def test_map_category_string_electric_guitar(db_session, mocker):
    mock_settings = MagicMock()
    mock_settings.EBAY_SANDBOX_MODE = False

    service = EbayService(db_session, mock_settings)
    result = service._map_category_string_to_ebay("Electric Guitar")

    assert result is not None
    assert result.get("CategoryID") == "33034"


@pytest.mark.asyncio
async def test_map_category_string_bass_guitar(db_session, mocker):
    mock_settings = MagicMock()
    mock_settings.EBAY_SANDBOX_MODE = False

    service = EbayService(db_session, mock_settings)
    result = service._map_category_string_to_ebay("Bass Guitar")

    assert result is not None
    assert result.get("CategoryID") == "4713"


@pytest.mark.asyncio
async def test_map_category_string_amplifier(db_session, mocker):
    mock_settings = MagicMock()
    mock_settings.EBAY_SANDBOX_MODE = False

    service = EbayService(db_session, mock_settings)
    result = service._map_category_string_to_ebay("Guitar Amplifier")

    assert result is not None
    assert result.get("CategoryID") == "38072"


@pytest.mark.asyncio
async def test_sanitize_description_removes_brazilian_rosewood(db_session, mocker):
    mock_settings = MagicMock()
    mock_settings.EBAY_SANDBOX_MODE = False

    service = EbayService(db_session, mock_settings)
    result = service._sanitize_description_for_ebay("Beautiful guitar with Brazilian Rosewood fingerboard")

    assert "Brazilian Rosewood" not in result
    assert "Rosewood" in result


@pytest.mark.asyncio
async def test_sanitize_description_handles_none(db_session, mocker):
    mock_settings = MagicMock()
    mock_settings.EBAY_SANDBOX_MODE = False

    service = EbayService(db_session, mock_settings)
    result = service._sanitize_description_for_ebay(None)
    assert result is None


@pytest.mark.asyncio
async def test_sanitize_description_no_changes_needed(db_session, mocker):
    mock_settings = MagicMock()
    mock_settings.EBAY_SANDBOX_MODE = False

    service = EbayService(db_session, mock_settings)
    desc = "A great guitar with Indian Rosewood fingerboard"
    result = service._sanitize_description_for_ebay(desc)
    assert result == desc


@pytest.mark.asyncio
async def test_normalize_get_item_response_with_item_key(db_session, mocker):
    mock_settings = MagicMock()
    mock_settings.EBAY_SANDBOX_MODE = False

    service = EbayService(db_session, mock_settings)
    response = {"Item": {"ItemID": "123", "Title": "Test Guitar"}}
    result = service._normalize_get_item_response(response)
    assert result == response
    assert "Item" in result


@pytest.mark.asyncio
async def test_normalize_get_item_response_with_none(db_session, mocker):
    mock_settings = MagicMock()
    mock_settings.EBAY_SANDBOX_MODE = False

    service = EbayService(db_session, mock_settings)
    result = service._normalize_get_item_response(None)
    assert result is None
