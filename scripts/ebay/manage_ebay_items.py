#!/usr/bin/env python3
"""
CLI script to manage eBay items using Trading API endpoints.
Usage: 
    python scripts/ebay/manage_ebay_items.py end [item_ids...] 
    python scripts/ebay/manage_ebay_items.py relist [item_ids...]

Examples:

# End listings
    python scripts/ebay/manage_ebay_items.py end --dry-run 123456789 123456790
    python scripts/ebay/manage_ebay_items.py end --verify 123456789 123456790
    python scripts/ebay/manage_ebay_items.py end --reason LostOrBroken 123456789

# Relist items  
    python scripts/ebay/manage_ebay_items.py relist --dry-run 123456789
    python scripts/ebay/manage_ebay_items.py relist 123456789

# Test in sandbox
    python scripts/ebay/manage_ebay_items.py end --sandbox 123456789

End Listing Reason codes:
    NotAvailable - Item is no longer available
    LostOrBroken - Item is lost or broken
    Incorrect - Listing contains errors
    OtherListingError - Other listing error
    CustomCode - Custom ending reason
    SellToHighBidder - Sell to highest bidder (auctions)


"""

import argparse
import asyncio
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
load_dotenv()

from app.services.ebay.trading import EbayTradingLegacyAPI

class EbayItemManager:
    """Manager for eBay item operations"""
    
    def __init__(self, sandbox: bool = False):
        self.api = EbayTradingLegacyAPI(sandbox=sandbox)
        self.sandbox = sandbox
    
    async def end_listing(self, item_id: str, reason: str = "NotAvailable") -> dict:
        """End a single eBay listing"""
        try:
            print(f"🔚 Ending eBay listing: {item_id} (reason: {reason})")
            
            response = await self.api.end_listing(item_id, reason)
            
            # Check eBay response
            if response and "EndItemResponse" in response:
                end_response = response["EndItemResponse"]
                ack = end_response.get("Ack", "")
                
                if ack in ["Success", "Warning"]:
                    end_time = end_response.get("EndTime", "")
                    print(f"✅ Successfully ended listing {item_id}")
                    if end_time:
                        print(f"   End time: {end_time}")
                    
                    return {
                        "success": True,
                        "item_id": item_id,
                        "end_time": end_time,
                        "response": end_response
                    }
                else:
                    # Handle eBay errors
                    errors = end_response.get("Errors", [])
                    if not isinstance(errors, list):
                        errors = [errors]
                    
                    error_messages = []
                    for error in errors:
                        error_messages.append(error.get("LongMessage", "Unknown error"))
                    
                    error_str = "; ".join(error_messages)
                    print(f"❌ eBay error ending {item_id}: {error_str}")
                    
                    return {
                        "success": False,
                        "error": error_str,
                        "item_id": item_id
                    }
            else:
                print(f"❌ Invalid response ending {item_id}")
                return {
                    "success": False,
                    "error": "Invalid response from eBay",
                    "item_id": item_id
                }
                
        except Exception as e:
            print(f"❌ Error ending {item_id}: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "item_id": item_id
            }
    
    async def relist_item(self, item_id: str) -> dict:
        """Relist an ended eBay item"""
        try:
            print(f"🔄 Relisting eBay item: {item_id}")
            
            response = await self.api.relist_item(item_id)
            
            if response and response.get("Ack") in ["Success", "Warning"]:
                new_item_id = response.get("ItemID")
                print(f"✅ Successfully relisted as {new_item_id}")
                
                return {
                    "success": True,
                    "original_item_id": item_id,
                    "new_item_id": new_item_id,
                    "response": response
                }
            else:
                errors = response.get("Errors", [])
                if not isinstance(errors, list):
                    errors = [errors]
                
                error_messages = []
                for error in errors:
                    error_messages.append(error.get("LongMessage", "Unknown error"))
                
                error_str = "; ".join(error_messages)
                print(f"❌ Error relisting {item_id}: {error_str}")
                
                return {
                    "success": False,
                    "error": error_str,
                    "item_id": item_id
                }
                
        except Exception as e:
            print(f"❌ Error relisting {item_id}: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "item_id": item_id
            }
    
    async def verify_listing_status(self, item_id: str, action: str) -> bool:
        """Verify if an action was successful"""
        try:
            item_details = await self.api.get_item_details(item_id)
            
            if action == "end":
                # Check if listing is ended
                status = item_details.get("SellingStatus", {}).get("ListingStatus", "")
                return status not in ["Active", ""]
            elif action == "relist":
                # For relist, the new item should be active
                status = item_details.get("SellingStatus", {}).get("ListingStatus", "")
                return status == "Active"
            
            return False
            
        except Exception as e:
            print(f"⚠️ Could not verify {item_id}: {str(e)}")
            return False
    
    async def process_items(self, item_ids: list, action: str, reason: str = "NotAvailable", verify: bool = False) -> dict:
        """Process multiple eBay items"""
        results = {
            "total": len(item_ids),
            "successful": 0,
            "failed": 0,
            "verified": 0,
            "details": []
        }
        
        for item_id in item_ids:
            if action == "end":
                result = await self.end_listing(item_id, reason)
            elif action == "relist":
                result = await self.relist_item(item_id)
            else:
                result = {"success": False, "error": f"Unknown action: {action}", "item_id": item_id}
            
            is_successful = result.get("success", False)
            
            # If verification requested and action seemed successful, verify
            if verify and is_successful:
                await asyncio.sleep(2)  # Wait for eBay to process
                if await self.verify_listing_status(item_id, action):
                    result["verified"] = True
                    results["verified"] += 1
                else:
                    result["verified"] = False
                    is_successful = False
                    
            results["details"].append(result)
            
            if is_successful:
                results["successful"] += 1
            else:
                results["failed"] += 1
                
            # Small delay between operations
            await asyncio.sleep(1)
        
        return results

async def main():
    parser = argparse.ArgumentParser(description='Manage eBay items via Trading API')
    parser.add_argument('action', choices=['end', 'relist'], help='Action to perform')
    parser.add_argument('item_ids', nargs='+', help='eBay item IDs to process')
    parser.add_argument('--reason', default='NotAvailable', 
                        choices=['NotAvailable', 'LostOrBroken', 'Incorrect', 'OtherListingError'],
                        help='Reason for ending listings (default: NotAvailable)')
    parser.add_argument('--sandbox', action='store_true', help='Use eBay sandbox environment')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without doing it')
    parser.add_argument('--verify', action='store_true', help='Verify actions by checking item status afterwards')
    
    args = parser.parse_args()
    
    if args.dry_run:
        action_text = "end" if args.action == "end" else "relist"
        print(f"🔍 DRY RUN MODE - Would {action_text} these eBay listings:")
        for item_id in args.item_ids:
            print(f"  - {item_id}")
        if args.action == "end":
            print(f"  Reason: {args.reason}")
        print(f"Total: {len(args.item_ids)} items")
        print(f"Environment: {'Sandbox' if args.sandbox else 'Production'}")
        return
    
    # Create manager
    manager = EbayItemManager(sandbox=args.sandbox)
    
    # Show environment
    env_text = "🧪 SANDBOX" if args.sandbox else "🔴 PRODUCTION"
    print(f"{env_text} environment")
    
    # Process items
    action_text = "ending" if args.action == "end" else "relisting"
    action_past = "ENDED" if args.action == "end" else "RELISTED"
    
    print(f"\n🔄 Starting {action_text} of {len(args.item_ids)} eBay items...")
    
    if args.verify:
        print("🔍 Verification enabled - will check each item after processing")
    
    try:
        results = await manager.process_items(args.item_ids, args.action, args.reason, args.verify)
    except Exception as e:
        print(f"❌ Critical error during {action_text}: {str(e)}")
        return
    
    # Print summary
    print(f"\n📊 **{action_past} SUMMARY**")
    print("=" * 50)
    print(f"Total items processed: {results['total']}")
    print(f"✅ Successful: {results['successful']}")
    print(f"❌ Failed: {results['failed']}")
    
    if args.verify and 'verified' in results:
        print(f"🔍 Verified successful: {results['verified']}")
    
    # Show failure details
    if results['failed'] > 0:
        print(f"\n❌ **FAILED {action_past} OPERATIONS:**")
        for detail in results['details']:
            if not detail['success']:
                error_msg = detail.get('error', 'Unknown error')
                print(f"  - {detail['item_id']}: {error_msg}")
    
    # Final status message
    if results['failed'] == 0:
        print(f"\n🎉 All {results['successful']} items successfully {action_text}!")
    elif results['successful'] == 0:
        print(f"\n💥 All {results['failed']} {action_text} operations failed!")
    else:
        print(f"\n⚖️ Mixed results: {results['successful']} succeeded, {results['failed']} failed")

if __name__ == '__main__':
    asyncio.run(main())