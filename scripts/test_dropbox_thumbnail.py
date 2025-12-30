#!/usr/bin/env python3
"""
Test script for the new Dropbox thumbnail API integration.
Tests:
1. Get thumbnail (actual bytes) via /get_thumbnail_v2
2. Get thumbnail as data URL for embedding
3. Get full-res link on demand
"""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / '.env')


async def test_thumbnail_api():
    from app.services.dropbox.dropbox_async_service import AsyncDropboxClient

    # Get credentials
    access_token = os.environ.get('DROPBOX_ACCESS_TOKEN')
    refresh_token = os.environ.get('DROPBOX_REFRESH_TOKEN')
    app_key = os.environ.get('DROPBOX_APP_KEY')
    app_secret = os.environ.get('DROPBOX_APP_SECRET')

    if not access_token and not refresh_token:
        print("❌ No Dropbox credentials found in environment")
        return False

    print("✅ Creating Dropbox client...")
    client = AsyncDropboxClient(
        access_token=access_token,
        refresh_token=refresh_token,
        app_key=app_key,
        app_secret=app_secret
    )

    # Test connection
    print("\n📡 Testing connection...")
    if not await client.test_connection():
        print("❌ Failed to connect to Dropbox")
        return False
    print("✅ Connected to Dropbox")

    # Get a list of images to test with
    print("\n📂 Scanning for test images (recursive, this may take a moment)...")
    import aiohttp
    async with aiohttp.ClientSession() as session:
        # List folders recursively to find an image
        entries = await client.list_folder_recursive("")

        # Find first image file
        test_image = None
        image_count = 0
        for entry in entries:
            if entry.get('.tag') == 'file':
                path = entry.get('path_lower', '')
                if any(path.endswith(ext) for ext in ['.jpg', '.jpeg', '.png']):
                    image_count += 1
                    if not test_image:
                        test_image = path
                        print(f"✅ Found image: {path}")

        print(f"📊 Total images found: {image_count}")

        if not test_image:
            print("❌ No image files found in Dropbox. Cannot test thumbnail API.")
            return False

        print(f"\n🖼️  Testing thumbnail for: {test_image}")

        # Test 1: Get thumbnail bytes
        print("\n--- Test 1: Get thumbnail bytes ---")
        path, thumb_bytes = await client.get_thumbnail(session, test_image, "w256h256")
        if thumb_bytes:
            print(f"✅ Got thumbnail: {len(thumb_bytes)} bytes")
        else:
            print("❌ Failed to get thumbnail bytes")
            # This might fail if the file doesn't exist - try to continue

        # Test 2: Get thumbnail as data URL
        print("\n--- Test 2: Get thumbnail as data URL ---")
        path, data_url = await client.get_thumbnail_as_data_url(session, test_image, "w256h256")
        if data_url:
            print(f"✅ Got data URL: {data_url[:80]}...")
            print(f"   Length: {len(data_url)} chars")
        else:
            print("❌ Failed to get thumbnail data URL")

        # Test 3: Get full-res link
        print("\n--- Test 3: Get full-res link (lazy fetch) ---")
        full_link = await client.get_full_res_link(test_image)
        if full_link:
            print(f"✅ Got full-res link: {full_link[:80]}...")
        else:
            print("❌ Failed to get full-res link")

        # Test 4: Compare sizes
        if thumb_bytes and full_link:
            print("\n--- Test 4: Compare thumbnail vs full-res ---")
            async with session.get(full_link) as resp:
                if resp.status == 200:
                    full_bytes = await resp.read()
                    print(f"📊 Thumbnail: {len(thumb_bytes):,} bytes")
                    print(f"📊 Full-res:  {len(full_bytes):,} bytes")
                    print(f"📊 Savings:   {(1 - len(thumb_bytes)/len(full_bytes))*100:.1f}%")

    print("\n✅ All tests completed!")
    return True


if __name__ == "__main__":
    success = asyncio.run(test_thumbnail_api())
    sys.exit(0 if success else 1)
