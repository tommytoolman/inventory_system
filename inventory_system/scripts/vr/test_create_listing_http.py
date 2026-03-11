#!/usr/bin/env python3
"""
Test script for the new create_listing_http method.

This tests the HTTP-based listing creation without Selenium.
Run with test_mode=True to validate the form data without actually submitting.
"""

import asyncio
import os
import sys

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv()

from app.services.vintageandrare.client import VintageAndRareClient


async def test_create_listing_http():
    """Test the HTTP-based listing creation in test mode."""

    username = os.environ.get('VINTAGE_AND_RARE_USERNAME')
    password = os.environ.get('VINTAGE_AND_RARE_PASSWORD')

    if not username or not password:
        print("ERROR: Set VINTAGE_AND_RARE_USERNAME and VINTAGE_AND_RARE_PASSWORD")
        return

    print("=" * 60)
    print("Testing create_listing_http (test mode)")
    print("=" * 60)

    client = VintageAndRareClient(username, password)

    # Test product data
    test_product = {
        'sku': 'TEST-HTTP-001',
        'brand': 'Fender',
        'model': 'Stratocaster Test',
        'year': '1965',
        'finish': 'Sunburst',
        'price': '9999',
        'description': '<p>This is a test listing created via HTTP.</p>',
        'Category': '51',  # Guitars
        'SubCategory1': '83',  # Electric Guitars
        'processing_time': '3',
        'time_unit': 'Days',
        'available_for_shipment': True,
        # Test with a sample image URL
        'primary_image': 'https://images.reverb.com/image/upload/s--test--/a_0/v1234567890/test_image.jpg',
    }

    print("\nTest product data:")
    for key, value in test_product.items():
        print(f"  {key}: {value}")

    print("\n" + "-" * 60)
    print("Calling create_listing_http with test_mode=True...")
    print("-" * 60)

    result = await client.create_listing_http(
        product_data=test_product,
        test_mode=True,  # Don't actually submit
        from_scratch=False
    )

    print("\nResult:")
    print(f"  Status: {result.get('status')}")
    print(f"  Message: {result.get('message')}")

    if result.get('status') == 'test':
        print(f"  Image count: {result.get('image_count', 0)}")
        print(f"\n  Form fields prepared: {len(result.get('form_data', {}))}")

        # Show key form fields
        form_data = result.get('form_data', {})
        key_fields = ['recipient_name', 'model_name', 'year', 'decade', 'price',
                      'item_desc', 'categ_level_0', 'categ_level_1', 'external_id',
                      'unique_id', 'version']

        print("\n  Key form fields:")
        for field in key_fields:
            value = form_data.get(field, '<not set>')
            if isinstance(value, str) and len(value) > 50:
                value = value[:50] + '...'
            print(f"    {field}: {value}")

    elif result.get('status') == 'error':
        print(f"  Error details: {result.get('body', result.get('message'))}")

    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)


if __name__ == '__main__':
    asyncio.run(test_create_listing_http())
