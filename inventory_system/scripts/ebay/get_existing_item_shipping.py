#!/usr/bin/env python3
"""Get shipping details from an existing eBay listing to see valid service codes."""

import asyncio
import sys
from pathlib import Path
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.database import async_session
from app.services.ebay.trading import EbayTradingLegacyAPI
from sqlalchemy import text

async def get_existing_item_shipping():
    """Fetch an existing eBay listing to see its shipping configuration."""
    
    # Initialize trading API
    trading_api = EbayTradingLegacyAPI(sandbox=False)
    
    # First, let's find an existing eBay listing from the database
    async with async_session() as db:
        result = await db.execute(
            text("""
                SELECT pc.external_id, p.title
                FROM platform_common pc
                JOIN products p ON p.id = pc.product_id
                WHERE pc.platform_name = 'ebay'
                AND pc.status = 'ACTIVE'
                LIMIT 5
            """)
        )
        listings = result.fetchall()
        
        if not listings:
            print("No active eBay listings found in database")
            return
        
        print(f"Found {len(listings)} active eBay listings. Fetching details...\n")
        
        for listing in listings:
            item_id = listing.external_id
            title = listing.title
            
            print(f"\nFetching details for Item ID: {item_id}")
            print(f"Title: {title[:80]}...")
            print("-" * 80)
            
            # Get item details using GetItem call
            try:
                xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
                <GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
                    <RequesterCredentials>
                        <eBayAuthToken>{await trading_api._get_auth_token()}</eBayAuthToken>
                    </RequesterCredentials>
                    <ItemID>{item_id}</ItemID>
                    <IncludeItemSpecifics>true</IncludeItemSpecifics>
                    <DetailLevel>ItemReturnDescription</DetailLevel>
                </GetItemRequest>"""
                
                response = await trading_api._make_request('GetItem', xml_request)
                
                if response and 'GetItemResponse' in response:
                    item_response = response['GetItemResponse']
                    
                    if item_response.get('Ack') in ('Success', 'Warning'):
                        item = item_response.get('Item', {})
                        
                        # Extract shipping details
                        shipping_details = item.get('ShippingDetails', {})
                        
                        print("\nSHIPPING CONFIGURATION:")
                        print(f"  Shipping Type: {shipping_details.get('ShippingType')}")
                        
                        # Domestic shipping
                        print("\n  DOMESTIC SHIPPING:")
                        domestic_options = shipping_details.get('ShippingServiceOptions', [])
                        if not isinstance(domestic_options, list):
                            domestic_options = [domestic_options] if domestic_options else []
                        
                        for i, option in enumerate(domestic_options):
                            print(f"    Option {i+1}:")
                            print(f"      Service: {option.get('ShippingService')}")
                            print(f"      Cost: {option.get('ShippingServiceCost', {}).get('#text', 'N/A')}")
                            print(f"      Priority: {option.get('ShippingServicePriority')}")
                        
                        # International shipping
                        print("\n  INTERNATIONAL SHIPPING:")
                        intl_options = shipping_details.get('InternationalShippingServiceOption', [])
                        if not isinstance(intl_options, list):
                            intl_options = [intl_options] if intl_options else []
                        
                        for i, option in enumerate(intl_options):
                            print(f"    Option {i+1}:")
                            print(f"      Service: {option.get('ShippingService')}")
                            print(f"      Cost: {option.get('ShippingServiceCost', {}).get('#text', 'N/A')}")
                            print(f"      Priority: {option.get('ShippingServicePriority')}")
                            print(f"      Ship To: {option.get('ShipToLocation')}")
                        
                        # Also check if using business policies
                        seller_profiles = item.get('SellerProfiles', {})
                        if seller_profiles:
                            print("\n  BUSINESS POLICIES IN USE:")
                            if 'SellerShippingProfile' in seller_profiles:
                                print(f"    Shipping Profile ID: {seller_profiles['SellerShippingProfile'].get('ShippingProfileID')}")
                                print(f"    Shipping Profile Name: {seller_profiles['SellerShippingProfile'].get('ShippingProfileName')}")
                        
                        # Save full shipping details to file for reference
                        filename = f"ebay_shipping_example_{item_id}.json"
                        with open(filename, 'w') as f:
                            json.dump(shipping_details, f, indent=2)
                        print(f"\n  Full shipping details saved to: {filename}")
                        
                        # Only fetch first item for now
                        break
                        
                    else:
                        print(f"  Error fetching item: {item_response.get('Errors')}")
                        
            except Exception as e:
                print(f"  Exception: {str(e)}")

async def main():
    await get_existing_item_shipping()

if __name__ == "__main__":
    asyncio.run(main())