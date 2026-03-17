# tests/unit/services/test_vintageandrare_service.py
"""
Tests for VRService.

Written against the ACTUAL VRService implementation.
The service has:
  - __init__(db)
  - run_import_process(username, password, sync_run_id, save_only=False)
  - sync_vr_inventory(df, sync_run_id)
  - _calculate_changes(api_items, db_items)
  - _has_changed(api_item, db_item)
  - _sanitize_for_json(obj)
  - _get_platform_status(product_id, platform_name)
"""
import math
import uuid
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest
from app.services.vintageandrare.client import VintageAndRareClient
from app.services.vr_service import VRService


@pytest.mark.asyncio
async def test_vr_service_initialization(db_session):
    """Test VRService initializes with db session."""
    service = VRService(db=db_session)
    assert service.db == db_session
    assert service.settings is not None


def test_sanitize_for_json_replaces_nan_with_none(db_session):
    """Test NaN values are replaced with None."""
    service = VRService(db=db_session)

    result = service._sanitize_for_json({"price": float("nan"), "name": "Guitar"})
    assert result["price"] is None
    assert result["name"] == "Guitar"


def test_sanitize_for_json_handles_nested(db_session):
    """Test nested structures are sanitized."""
    service = VRService(db=db_session)
    result = service._sanitize_for_json({"nested": {"price": float("nan")}})
    assert result["nested"]["price"] is None


def test_sanitize_for_json_handles_list(db_session):
    """Test lists are sanitized."""
    service = VRService(db=db_session)
    result = service._sanitize_for_json([float("nan"), "ok", 1.5])
    assert result[0] is None
    assert result[1] == "ok"
    assert result[2] == 1.5
    # Ensure math.isnan works as expected
    assert math.isnan(float("nan"))


def test_calculate_changes_detects_new_items(db_session):
    """Test that new active items are scheduled for creation."""
    service = VRService(db=db_session)

    api_items = {
        "101": {"vr_id": "101", "status": "active", "price": 1500.0, "sku": "VR-101"},
    }
    db_items = {}

    changes = service._calculate_changes(api_items, db_items)

    assert len(changes["create"]) == 1
    assert changes["create"][0]["vr_id"] == "101"
    assert len(changes["update"]) == 0
    assert len(changes["remove"]) == 0


def test_calculate_changes_skips_sold_new_items(db_session):
    """Test that sold items not in DB are NOT created."""
    service = VRService(db=db_session)

    api_items = {
        "102": {"vr_id": "102", "status": "sold", "price": 2500.0},
    }
    db_items = {}

    changes = service._calculate_changes(api_items, db_items)

    assert len(changes["create"]) == 0


def test_calculate_changes_detects_removals(db_session):
    """Test that items in DB but not in API are flagged for removal."""
    service = VRService(db=db_session)

    api_items = {}
    db_items = {
        "999": {
            "vr_id": "999",
            "platform_common_status": "active",
            "product_id": 1,
        }
    }

    changes = service._calculate_changes(api_items, db_items)

    assert len(changes["remove"]) == 1
    assert changes["remove"][0]["vr_id"] == "999"


def test_calculate_changes_skips_already_inactive_removals(db_session):
    """Test that inactive items in DB are not re-flagged for removal."""
    service = VRService(db=db_session)

    api_items = {}
    db_items = {
        "999": {
            "vr_id": "999",
            "platform_common_status": "ended",
            "product_id": 1,
        }
    }

    changes = service._calculate_changes(api_items, db_items)

    assert len(changes["remove"]) == 0


@pytest.mark.asyncio
async def test_run_import_process_authentication_failure(db_session, mocker):
    """Test run_import_process returns error when auth fails."""
    service = VRService(db=db_session)
    sync_run_id = uuid.uuid4()

    mock_client = MagicMock(spec=VintageAndRareClient)
    mock_client.authenticate = AsyncMock(return_value=False)
    mock_client.cleanup_temp_files = MagicMock()

    mocker.patch("app.services.vr_service.VintageAndRareClient", return_value=mock_client)

    result = await service.run_import_process("user", "pass", sync_run_id)

    assert result["status"] == "error"
    assert "authentication" in result["message"].lower()


@pytest.mark.asyncio
async def test_run_import_process_save_only(db_session, mocker):
    """Test save_only mode returns count without syncing."""
    service = VRService(db=db_session)
    sync_run_id = uuid.uuid4()

    mock_df = pd.DataFrame({"product_id": ["101", "102"], "brand_name": ["Fender", "Gibson"]})
    mock_client = MagicMock(spec=VintageAndRareClient)
    mock_client.authenticate = AsyncMock(return_value=True)
    mock_client.download_inventory_dataframe = AsyncMock(return_value=mock_df)
    mock_client.cleanup_temp_files = MagicMock()

    mocker.patch("app.services.vr_service.VintageAndRareClient", return_value=mock_client)

    result = await service.run_import_process("user", "pass", sync_run_id, save_only=True)

    assert result["status"] == "success"
    assert result["count"] == 2


@pytest.mark.asyncio
async def test_run_import_process_empty_download(db_session, mocker):
    """Test run_import_process returns error on empty download."""
    service = VRService(db=db_session)
    sync_run_id = uuid.uuid4()

    mock_client = MagicMock(spec=VintageAndRareClient)
    mock_client.authenticate = AsyncMock(return_value=True)
    mock_client.download_inventory_dataframe = AsyncMock(return_value=None)
    mock_client.cleanup_temp_files = MagicMock()

    mocker.patch("app.services.vr_service.VintageAndRareClient", return_value=mock_client)

    result = await service.run_import_process("user", "pass", sync_run_id)

    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_run_import_process_retry_needed(db_session, mocker):
    """Test run_import_process handles RETRY_NEEDED signal."""
    service = VRService(db=db_session)
    sync_run_id = uuid.uuid4()

    mock_client = MagicMock(spec=VintageAndRareClient)
    mock_client.authenticate = AsyncMock(return_value=True)
    mock_client.download_inventory_dataframe = AsyncMock(return_value="RETRY_NEEDED")
    mock_client.cleanup_temp_files = MagicMock()

    mocker.patch("app.services.vr_service.VintageAndRareClient", return_value=mock_client)

    result = await service.run_import_process("user", "pass", sync_run_id)

    assert result["status"] == "retry_needed"
