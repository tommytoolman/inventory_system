# tests/integration/test_cli_import_vr.py

import os
import pytest
# Remove CliRunner import if no longer needed
# from click.testing import CliRunner
from unittest.mock import patch # To mock filesystem if desired
from sqlalchemy import select, func
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession

# --- Import the CORE LOGIC function, not the click command ---
from app.cli.import_vr import _run_import_logic
# --- ---
from app.models.product import Product
from app.models.platform_common import PlatformCommon
from app.models.vr import VRListing

# Requires db_session fixture from tests/conftest.py automatically

VR_USER = os.environ.get("VINTAGE_AND_RARE_USERNAME")
VR_PASS = os.environ.get("VINTAGE_AND_RARE_PASSWORD")

# Remove runner fixture if no longer used
# @pytest.fixture
# def runner():
#    """Provides a CliRunner instance."""
#    return CliRunner()

@pytest.mark.skipif(not VR_USER or not VR_PASS, reason="V&R credentials not set in environment")
@pytest.mark.integration
async def test_cli_import_vr_e2e(db_session: AsyncSession): # Test receives the correct session
    """
    Test the core async logic of the `import-vr` command end-to-end.
    Uses the TEST session fixture.
    """
    with patch('shutil.copy2') as mock_copy:
        print("\nAwaiting _run_import_logic...")
        # --- Pass the db_session fixture to the logic function ---
        success, stats = await _run_import_logic(db_session, VR_USER, VR_PASS, save_only=False)
        # --- ---

        # --- Assertions ---
        print("\n--- Result ---")
        print(f"Success: {success}")
        print(f"Stats: {stats}")
        print("--- End Result ---")

        assert success is True, f"Import logic failed. Stats: {stats}"
        assert stats is not None
        assert "error" not in stats
        assert "created" in stats and stats["created"] > 0 # Check created count specifically

        mock_copy.assert_called_once()

        # Assert Database State (Now using the same session)
        print("\nChecking database state...")
        # No need for db_session.begin() here if commit happened in logic function
        # Query directly using the db_session
        product_count_res = await db_session.execute(select(func.count(Product.id)).where(Product.sku.like('VR-%')))
        product_count = product_count_res.scalar_one()

        # ... other DB count queries ...
        platform_count_res = await db_session.execute(select(func.count(PlatformCommon.id)).where(PlatformCommon.platform_name == 'vintageandrare'))
        platform_count = platform_count_res.scalar_one()
        vr_listing_count_res = await db_session.execute(select(func.count(VRListing.id)))
        vr_listing_count = vr_listing_count_res.scalar_one()


        print(f"DB Counts Found: Products={product_count}, PlatformCommon={platform_count}, VRListing={vr_listing_count}")
        assert product_count > 0, "Expected some VR products to be imported"
        assert product_count == platform_count
        assert platform_count == vr_listing_count
        # Compare DB count with stats reported
        assert product_count == stats['created'], f"DB count ({product_count}) does not match reported created count ({stats['created']})"


@pytest.mark.skipif(not VR_USER or not VR_PASS, reason="V&R credentials not set in environment")
@pytest.mark.integration
async def test_cli_import_vr_save_only_e2e(db_session: AsyncSession): # Test receives the correct session
    """Test `import-vr --save-only` mode by calling core logic."""
    with patch('shutil.copy2') as mock_copy:
        print("\nAwaiting _run_import_logic with save_only=True...")
         # --- Pass the db_session fixture (though it won't be used for writes) ---
        success, stats = await _run_import_logic(db_session, VR_USER, VR_PASS, save_only=True)
         # --- ---

        print("\n--- Result ---")
        print(f"Success: {success}")
        print(f"Stats: {stats}")
        print("--- End Result ---")

        assert success is True, f"Save-only logic failed. Stats: {stats}"
        assert stats is not None
        assert "error" not in stats
        assert "saved_to" in stats

        mock_copy.assert_called_once()

        # Assert Database State (Should be unchanged)
        print("\nChecking database state (should be empty)...")
        # No need for db_session.begin()
        product_count_res = await db_session.execute(select(func.count(Product.id)).where(Product.sku.like('VR-%')))
        product_count = product_count_res.scalar_one()
        assert product_count == 0, "Database should remain empty in save-only mode"


