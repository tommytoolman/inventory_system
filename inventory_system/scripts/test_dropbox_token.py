#!/usr/bin/env python3
"""Test Dropbox token and refresh if needed"""

import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
from app.core.config import get_settings

async def test_dropbox_connection():
    """Test Dropbox connection and token refresh"""
    settings = get_settings()

    print("\n=== Testing Dropbox Connection ===")
    print(f"Access token exists: {bool(settings.DROPBOX_ACCESS_TOKEN)}")
    print(f"Refresh token exists: {bool(settings.DROPBOX_REFRESH_TOKEN)}")
    print(f"App key exists: {bool(settings.DROPBOX_APP_KEY)}")
    print(f"App secret exists: {bool(settings.DROPBOX_APP_SECRET)}")

    # Initialize service
    dropbox_service = AsyncDropboxClient(
        access_token=settings.DROPBOX_ACCESS_TOKEN,
        refresh_token=settings.DROPBOX_REFRESH_TOKEN,
        app_key=settings.DROPBOX_APP_KEY,
        app_secret=settings.DROPBOX_APP_SECRET
    )

    # Test connection
    print("\n1. Testing current token...")
    try:
        # Try a simple API call
        result = await dropbox_service.get_folder_contents("/")
        print(f"✓ Current token is valid. Found {len(result.get('entries', []))} items in root folder")
        return True
    except Exception as e:
        print(f"✗ Current token failed: {e}")

    # Try token refresh
    print("\n2. Attempting token refresh...")
    try:
        success = await dropbox_service.refresh_access_token()
        if success:
            print("✓ Token refresh successful!")
            print(f"New access token (first 20 chars): {dropbox_service.access_token[:20]}...")

            # Test the new token
            result = await dropbox_service.get_folder_contents("/")
            print(f"✓ New token works! Found {len(result.get('entries', []))} items in root folder")

            # Print the full token so user can update .env
            print("\n" + "="*80)
            print("UPDATE YOUR .env FILE WITH THIS NEW TOKEN:")
            print(f"DROPBOX_ACCESS_TOKEN={dropbox_service.access_token}")
            print("="*80)

            return True
        else:
            print("✗ Token refresh failed")
            return False
    except Exception as e:
        print(f"✗ Token refresh error: {e}")
        return False

if __name__ == "__main__":
    asyncio.run(test_dropbox_connection())