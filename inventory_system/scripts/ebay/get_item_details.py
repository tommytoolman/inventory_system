#!/usr/bin/env python3
"""
Script to get eBay item details for a single item ID

Usage:
    python get_item_details.py <item_id> [--sandbox] [--output json|pretty]

Examples:
    python get_item_details.py 123456789012
    python get_item_details.py 123456789012 --sandbox
    python get_item_details.py 123456789012 --output json
"""

import sys
import os
import asyncio
import argparse
import json
from pathlib import Path

# Add the parent directory to Python path so we can import from app/
sys.path.append(str(Path(__file__).parent.parent))

from app.services.ebay.trading import EbayTradingLegacyAPI


async def get_item_details(item_id: str, sandbox: bool = False, output_format: str = 'pretty'):
    """
    Get detailed information for a specific eBay item
    
    Args:
        item_id: The eBay item ID to lookup
        sandbox: Whether to use sandbox environment
        output_format: Output format ('json' or 'pretty')
    """
    try:
        # Initialize the eBay Trading API
        ebay_api = EbayTradingLegacyAPI(sandbox=sandbox)
        
        print(f"Fetching details for item ID: {item_id}")
        if sandbox:
            print("Using SANDBOX environment")
        else:
            print("Using PRODUCTION environment")
        
        # Get item details
        item_details = await ebay_api.get_item_details(item_id)
        
        if not item_details:
            print(f"No details found for item ID: {item_id}")
            return None
        
        # Output based on format preference
        if output_format == 'json':
            print(json.dumps(item_details, indent=2, default=str))
        else:
            # Pretty formatted output
            print("\n" + "="*60)
            print("ITEM DETAILS")
            print("="*60)
            
            # Basic info
            print(f"Item ID: {item_details.get('ItemID', 'N/A')}")
            print(f"Title: {item_details.get('Title', 'N/A')}")
            print(f"Condition: {item_details.get('ConditionDisplayName', 'N/A')}")
            
            # Price info
            selling_status = item_details.get('SellingStatus', {})
            if selling_status:
                current_price = selling_status.get('CurrentPrice', {})
                if isinstance(current_price, dict):
                    price_text = current_price.get('#text', 'N/A')
                    currency = current_price.get('@currencyID', '')
                    print(f"Current Price: {price_text} {currency}")
                else:
                    print(f"Current Price: {current_price}")
                
                print(f"Listing Status: {selling_status.get('ListingStatus', 'N/A')}")
                print(f"Quantity Available: {selling_status.get('QuantityAvailable', 'N/A')}")
            
            # Category
            primary_category = item_details.get('PrimaryCategory', {})
            if primary_category:
                print(f"Category: {primary_category.get('CategoryName', 'N/A')} (ID: {primary_category.get('CategoryID', 'N/A')})")
            
            # Location and shipping
            print(f"Location: {item_details.get('Location', 'N/A')}")
            print(f"Country: {item_details.get('Country', 'N/A')}")
            
            # Timing
            print(f"Start Time: {item_details.get('ListingDetails', {}).get('StartTime', 'N/A')}")
            print(f"End Time: {item_details.get('ListingDetails', {}).get('EndTime', 'N/A')}")
            
            # Item specifics
            item_specifics = item_details.get('ItemSpecifics', {}).get('NameValueList', [])
            if item_specifics:
                print(f"\nITEM SPECIFICS:")
                print("-" * 20)
                # Handle both single item and list of items
                if isinstance(item_specifics, list):
                    for spec in item_specifics:
                        name = spec.get('Name', 'Unknown')
                        value = spec.get('Value', 'N/A')
                        # Handle multiple values
                        if isinstance(value, list):
                            value = ', '.join(value)
                        print(f"{name}: {value}")
                else:
                    # Single item specific
                    name = item_specifics.get('Name', 'Unknown')
                    value = item_specifics.get('Value', 'N/A')
                    if isinstance(value, list):
                        value = ', '.join(value)
                    print(f"{name}: {value}")
            
            # Shipping details
            shipping_details = item_details.get('ShippingDetails', {})
            if shipping_details:
                print(f"\nSHIPPING DETAILS:")
                print("-" * 20)
                print(f"Shipping Type: {shipping_details.get('ShippingType', 'N/A')}")
                print(f"Global Shipping: {shipping_details.get('GlobalShipping', 'N/A')}")
                print(f"Get It Fast: {shipping_details.get('GetItFast', 'N/A')}")
                
                # Shipping service options
                shipping_options = shipping_details.get('ShippingServiceOptions', [])
                if shipping_options:
                    if not isinstance(shipping_options, list):
                        shipping_options = [shipping_options]
                    
                    print(f"\nShipping Options ({len(shipping_options)}):")
                    for i, option in enumerate(shipping_options, 1):
                        priority = option.get('ShippingServicePriority', 'N/A')
                        service = option.get('ShippingService', 'N/A')
                        cost = option.get('ShippingServiceCost', {})
                        if isinstance(cost, dict):
                            cost_text = f"{cost.get('#text', '0')} {cost.get('@currencyID', '')}"
                        else:
                            cost_text = str(cost)
                        print(f"  {i}. {service} (Priority {priority}): {cost_text}")
                        
                        # Additional shipping details
                        add_cost = option.get('ShippingServiceAdditionalCost', {})
                        if add_cost and isinstance(add_cost, dict) and add_cost.get('#text'):
                            add_cost_text = f"{add_cost.get('#text')} {add_cost.get('@currencyID', '')}"
                            print(f"     Additional Item Cost: {add_cost_text}")
                
                # International shipping
                intl_shipping = shipping_details.get('InternationalShippingServiceOption', [])
                if intl_shipping:
                    if not isinstance(intl_shipping, list):
                        intl_shipping = [intl_shipping]
                    print(f"\nInternational Shipping Options ({len(intl_shipping)}):")
                    for i, option in enumerate(intl_shipping, 1):
                        service = option.get('ShippingService', 'N/A')
                        cost = option.get('ShippingServiceCost', {})
                        if isinstance(cost, dict):
                            cost_text = f"{cost.get('#text', '0')} {cost.get('@currencyID', '')}"
                        else:
                            cost_text = str(cost)
                        locations = option.get('ShipToLocation', 'N/A')
                        if isinstance(locations, list):
                            locations = ', '.join(locations)
                        print(f"  {i}. {service}: {cost_text} (Ships to: {locations})")
                
                # Handling time
                handling_time = shipping_details.get('HandlingTime', item_details.get('DispatchTimeMax'))
                if handling_time:
                    print(f"Handling Time: {handling_time} days")
            
            # Payment methods and policies
            payment_methods = item_details.get('PaymentMethods', [])
            if payment_methods:
                print(f"\nPAYMENT METHODS:")
                print("-" * 20)
                if isinstance(payment_methods, list):
                    for method in payment_methods:
                        print(f"• {method}")
                else:
                    print(f"• {payment_methods}")
            
            # PayPal email if present
            paypal_email = item_details.get('PayPalEmailAddress')
            if paypal_email:
                print(f"PayPal Email: {paypal_email}")
            
            # Return policy
            return_policy = item_details.get('ReturnPolicy', {})
            if return_policy:
                print(f"\nRETURN POLICY:")
                print("-" * 20)
                print(f"Returns Accepted: {return_policy.get('ReturnsAcceptedOption', 'N/A')}")
                print(f"Return Period: {return_policy.get('ReturnsWithinOption', 'N/A')}")
                print(f"Refund Method: {return_policy.get('RefundOption', 'N/A')}")
                print(f"Return Shipping Paid By: {return_policy.get('ShippingCostPaidByOption', 'N/A')}")
                
                # Return policy description
                return_desc = return_policy.get('Description')
                if return_desc:
                    print(f"Return Description: {return_desc}")
            
            # Business seller details
            business_details = item_details.get('BusinessSellerDetails', {})
            if business_details:
                print(f"\nBUSINESS SELLER INFO:")
                print("-" * 20)
                print(f"VAT ID: {business_details.get('VATID', 'N/A')}")
                print(f"Business Type: {business_details.get('BusinessType', 'N/A')}")
                
                address = business_details.get('Address', {})
                if address:
                    print(f"Business Address: {address.get('Street1', '')} {address.get('Street2', '')}")
                    print(f"  {address.get('CityName', '')} {address.get('StateOrProvince', '')} {address.get('PostalCode', '')}")
                    print(f"  {address.get('Country', '')}")
            
            # Cross border trade details
            cross_border = item_details.get('CrossBorderTrade', [])
            if cross_border:
                print(f"\nCROSS-BORDER TRADE:")
                print("-" * 20)
                if isinstance(cross_border, list):
                    for trade in cross_border:
                        print(f"• {trade}")
                else:
                    print(f"• {cross_border}")
            
            # Listing enhancements
            listing_enhancements = item_details.get('ListingEnhancement', [])
            if listing_enhancements:
                print(f"\nLISTING ENHANCEMENTS:")
                print("-" * 20)
                if isinstance(listing_enhancements, list):
                    for enhancement in listing_enhancements:
                        print(f"• {enhancement}")
                else:
                    print(f"• {listing_enhancements}")
            
            # Listing details (additional timing info)
            listing_details = item_details.get('ListingDetails', {})
            if listing_details:
                print(f"\nADDITIONAL LISTING DETAILS:")
                print("-" * 20)
                print(f"Listing Type: {item_details.get('ListingType', 'N/A')}")
                print(f"Listing Duration: {item_details.get('ListingDuration', 'N/A')}")
                print(f"Adult Only: {listing_details.get('Adult', 'false')}")
                print(f"Best Offer Enabled: {listing_details.get('BestOfferEnabled', 'false')}")
                print(f"Buy It Now Available: {listing_details.get('BuyItNowAvailable', 'false')}")
                print(f"Relisted Item ID: {listing_details.get('RelistedItemID', 'N/A')}")
                print(f"Second Category ID: {listing_details.get('SecondCategoryID', 'N/A')}")
            
            # Seller information
            seller = item_details.get('Seller', {})
            if seller:
                print(f"\nSELLER INFORMATION:")
                print("-" * 20)
                print(f"User ID: {seller.get('UserID', 'N/A')}")
                print(f"Feedback Score: {seller.get('FeedbackScore', 'N/A')}")
                print(f"Positive Feedback %: {seller.get('PositiveFeedbackPercent', 'N/A')}")
                print(f"Top Rated Seller: {seller.get('TopRatedSeller', 'N/A')}")
                print(f"eBay Good Standing: {seller.get('UserIDChanged', 'N/A')}")
                
                # Seller business info
                seller_info = seller.get('SellerInfo', {})
                if seller_info:
                    print(f"Store Owner: {seller_info.get('StoreOwner', 'N/A')}")
                    store_url = seller_info.get('StoreURL')
                    if store_url:
                        print(f"Store URL: {store_url}")
            
            # Quantity info
            quantity = item_details.get('Quantity', 'N/A')
            quantity_available = selling_status.get('QuantityAvailable', 'N/A') if selling_status else 'N/A'
            print(f"\nQUANTITY INFO:")
            print("-" * 20)
            print(f"Original Quantity: {quantity}")
            print(f"Available Quantity: {quantity_available}")
            print(f"Quantity Sold: {selling_status.get('QuantitySold', 'N/A') if selling_status else 'N/A'}")
            
            # Watch count and hit count
            if selling_status:
                watch_count = selling_status.get('WatchCount')
                hit_count = item_details.get('HitCount')
                if watch_count or hit_count:
                    print(f"\nENGAGEMENT:")
                    print("-" * 20)
                    if watch_count:
                        print(f"Watchers: {watch_count}")
                    if hit_count:
                        print(f"Views: {hit_count}")
            
            # Pictures
            picture_details = item_details.get('PictureDetails', {})
            if picture_details and 'PictureURL' in picture_details:
                picture_urls = picture_details['PictureURL']
                if isinstance(picture_urls, list):
                    print(f"\nPICTURES ({len(picture_urls)} found):")
                    print("-" * 20)
                    for i, url in enumerate(picture_urls, 1):
                        print(f"{i}: {url}")
                else:
                    print(f"\nPICTURE: {picture_urls}")
            
            # Description (truncated for readability)
            description = item_details.get('Description', '')
            if description:
                print(f"\nDESCRIPTION:")
                print("-" * 20)
                # Truncate long descriptions
                if len(description) > 300:
                    print(f"{description[:300]}...")
                    print(f"[Description truncated - full length: {len(description)} characters]")
                else:
                    print(description)
        
        return item_details
        
    except Exception as e:
        print(f"Error fetching item details: {str(e)}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description='Get eBay item details for a specific item ID',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s 123456789012
  %(prog)s 123456789012 --sandbox
  %(prog)s 123456789012 --output json
        """
    )
    
    parser.add_argument('item_id', help='eBay item ID to lookup')
    parser.add_argument('--sandbox', action='store_true', 
                       help='Use sandbox environment instead of production')
    parser.add_argument('--output', choices=['json', 'pretty'], default='pretty',
                       help='Output format (default: pretty)')
    
    args = parser.parse_args()
    
    # Validate item ID (basic check)
    if not args.item_id.isdigit():
        print(f"Error: Item ID should be numeric, got: {args.item_id}")
        sys.exit(1)
    
    # Run the async function
    asyncio.run(get_item_details(args.item_id, args.sandbox, args.output))


if __name__ == '__main__':
    main()