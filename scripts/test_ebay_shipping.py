#!/usr/bin/env python3
"""Test eBay shipping service codes to find valid ones."""

import os
import sys
import asyncio
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.ebay_service import EbayService
from app.database import async_session
import json

async def test_ebay_shipping():
    """Test different eBay shipping service codes."""
    
    async with async_session() as db:
        ebay_service = EbayService(db)
        
        # Test data
        test_item = {
            "Item": {
                "Title": "Test Guitar Listing",
                "Description": "This is a test listing",
                "PrimaryCategory": {"CategoryID": "33034"},  # Electric Guitars
                "StartPrice": "100.00",
                "ConditionID": "3000",  # Used
                "Country": "GB",
                "Currency": "GBP",
                "DispatchTimeMax": "3",
                "ListingDuration": "GTC",
                "ListingType": "FixedPriceItem",
                "PaymentMethods": "PayPal",
                "PayPalEmailAddress": os.getenv("PAYPAL_EMAIL", "test@example.com"),
                "PostalCode": "SW1A 1AA",
                "Quantity": "1",
                "ReturnPolicy": {
                    "ReturnsAcceptedOption": "ReturnsAccepted",
                    "RefundOption": "MoneyBack",
                    "ReturnsWithinOption": "Days_14",
                    "ShippingCostPaidByOption": "Buyer"
                },
                "Site": "UK",
                "SKU": "TEST-SHIPPING-001"
            }
        }
        
        print("Testing eBay Shipping Service Codes:\n" + "="*50)
        
        # Test different UK domestic services
        domestic_services = [
            # Currently used
            "UK_OtherCourier24",
            
            # Common alternatives
            "UK_RoyalMailFirstClassStandard",
            "UK_RoyalMailSecondClassStandard", 
            "UK_RoyalMailTracked24",
            "UK_RoyalMailTracked48",
            "UK_Parcelforce24",
            "UK_Parcelforce48",
            "UK_OtherCourier",
            "UK_OtherCourier3Days",
            "UK_SellersStandardRate",
            "UK_CollectInPerson",
            
            # Economy services
            "UK_EconomyShippingFromOutside",
            "UK_StandardShippingFromOutside",
            "UK_ExpeditedShippingFromOutside",
            
            # Other potential services
            "UK_myHermesDoorToDoorService",
            "UK_CollectDropAtStoreDeliveryToDoor"
        ]
        
        print("\n1. Testing DOMESTIC Services:\n" + "-"*40)
        valid_domestic = []
        
        for service_code in domestic_services:
            test_item_copy = json.loads(json.dumps(test_item))  # Deep copy
            test_item_copy["Item"]["ShippingDetails"] = {
                "ShippingType": "Flat",
                "ShippingServiceOptions": {
                    "ShippingServicePriority": "1",
                    "ShippingService": service_code,
                    "ShippingServiceCost": "10.00"
                }
            }
            
            try:
                response = await ebay_service.trading_api.verify_add_item(test_item_copy["Item"])
                print(f"  ✓ {service_code}")
                valid_domestic.append(service_code)
            except Exception as e:
                error_msg = str(e)
                if "ShippingService" in error_msg or "Invalid shipping service" in error_msg:
                    print(f"  ✗ {service_code} - INVALID")
                else:
                    # Check for other errors that might indicate format issues
                    if "Input data" in error_msg:
                        print(f"  ⚠ {service_code} - Format issue: {error_msg[:100]}")
                    else:
                        print(f"  ? {service_code} - Other: {error_msg[:80]}")
        
        # Test international services
        international_services = [
            # Currently used
            "UK_InternationalStandard",
            
            # Common alternatives
            "UK_RoyalMailInternationalStandard",
            "UK_RoyalMailInternationalTracked",
            "UK_RoyalMailInternationalSignedFor",
            "UK_ParcelForceInternationalStandard",
            "UK_ParcelForceInternationalEconomy", 
            "UK_ParcelForceInternationalExpress",
            "UK_OtherCourierOrDeliveryInternational",
            
            # Generic international
            "InternationalPriorityShipping",
            "StandardInternational",
            "ExpeditedInternational",
            "OtherInternational"
        ]
        
        print("\n2. Testing INTERNATIONAL Services:\n" + "-"*40)
        valid_international = []
        
        for service_code in international_services:
            test_item_copy = json.loads(json.dumps(test_item))  # Deep copy
            test_item_copy["Item"]["ShippingDetails"] = {
                "ShippingType": "Flat",
                "ShippingServiceOptions": {
                    "ShippingServicePriority": "1",
                    "ShippingService": "UK_RoyalMailFirstClassStandard",  # Valid domestic
                    "ShippingServiceCost": "10.00"
                },
                "InternationalShippingServiceOption": {
                    "ShippingServicePriority": "1", 
                    "ShippingService": service_code,
                    "ShippingServiceCost": "25.00",
                    "ShipToLocation": "Worldwide"
                }
            }
            
            try:
                response = await ebay_service.trading_api.verify_add_item(test_item_copy["Item"])
                print(f"  ✓ {service_code}")
                valid_international.append(service_code)
            except Exception as e:
                error_msg = str(e)
                if "ShippingService" in error_msg or "Invalid shipping service" in error_msg:
                    print(f"  ✗ {service_code} - INVALID")
                else:
                    if "Input data" in error_msg:
                        print(f"  ⚠ {service_code} - Format issue: {error_msg[:100]}")
                    else:
                        print(f"  ? {service_code} - Other: {error_msg[:80]}")
        
        # Test the exact format from _map_reverb_shipping_to_ebay
        print("\n3. Testing EXACT Format from ebay_service.py:\n" + "-"*40)
        
        # This is how the current code structures it
        test_item_copy = json.loads(json.dumps(test_item))
        test_item_copy["Item"]["ShippingDetails"] = {
            "ShippingType": "Flat",
            "ShippingServiceOptions": [
                {
                    "ShippingServicePriority": "1",
                    "ShippingService": "UK_OtherCourier24",
                    "ShippingServiceCost": "10.00"
                }
            ],
            "InternationalShippingServiceOption": [
                {
                    "ShippingServicePriority": "1",
                    "ShippingService": "UK_InternationalStandard",
                    "ShippingServiceCost": "25.00",
                    "ShipToLocation": "Worldwide"
                }
            ]
        }
        
        print("Testing with array format (current implementation):")
        try:
            response = ebay_service.client.execute('VerifyAddItem', test_item_copy)
            print("  ✓ Array format works!")
        except Exception as e:
            print(f"  ✗ Array format failed: {str(e)[:150]}")
        
        # Summary
        print("\n" + "="*50)
        print("SUMMARY:")
        print("="*50)
        if valid_domestic:
            print(f"\nValid DOMESTIC services ({len(valid_domestic)}):")
            for svc in valid_domestic:
                print(f"  • {svc}")
        
        if valid_international:
            print(f"\nValid INTERNATIONAL services ({len(valid_international)}):")
            for svc in valid_international:
                print(f"  • {svc}")

async def main():
    await test_ebay_shipping()

if __name__ == "__main__":
    asyncio.run(main())