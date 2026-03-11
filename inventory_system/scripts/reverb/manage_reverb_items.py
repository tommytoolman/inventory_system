#!/usr/bin/env python3
"""
CLI script to manage Reverb items using Reverb API.
Usage: 
    python scripts/reverb/manage_reverb_items.py end [listing_ids...] 
    python scripts/reverb/manage_reverb_items.py publish [listing_ids...]

Examples:

# End listings
    python scripts/reverb/manage_reverb_items.py end --dry-run 83653137 88526885 83403420 84343905 86848098 
    python scripts/reverb/manage_reverb_items.py end --verify 83653137 88526885 83403420 84343905 86848098 
    python scripts/reverb/manage_reverb_items.py end --reason reverb_sale 83653137 88526885 83403420 84343905 86848098 

# Publish draft listings  
    python scripts/reverb/manage_reverb_items.py publish --dry-run 83653137 88526885 83403420 84343905 86848098 
    python scripts/reverb/manage_reverb_items.py publish 83653137 88526885 83403420 84343905 86848098 

# Update listings
    python scripts/reverb/manage_reverb_items.py update 123430 --price 1500.00 --description "Updated description"
"""

import argparse
import asyncio
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Add the project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables from .env file
load_dotenv(project_root / '.env')

from app.services.reverb.client import ReverbClient

class ReverbItemManager:
    """Manager for Reverb item operations"""
    
    def __init__(self, api_key: str):
        self.client = ReverbClient(api_key)
    
    async def end_listing(self, listing_id: str, reason: str = "not_sold") -> dict:
        """End a single Reverb listing"""
        try:
            print(f"🛑 Ending listing ID: {listing_id} (reason: {reason})")
            
            result = await self.client.end_listing(listing_id, reason)
            
            print(f"✅ Successfully ended listing {listing_id}")
            return {"success": True, "response": result, "listing_id": listing_id}
            
        except Exception as e:
            print(f"❌ Error ending {listing_id}: {str(e)}")
            return {"success": False, "error": str(e), "listing_id": listing_id}
    
    async def publish_listing(self, listing_id: str) -> dict:
        """Publish a draft listing"""
        try:
            print(f"📢 Publishing listing ID: {listing_id}")
            
            result = await self.client.publish_listing(listing_id)
            
            print(f"✅ Successfully published listing {listing_id}")
            return {"success": True, "response": result, "listing_id": listing_id}
            
        except Exception as e:
            print(f"❌ Error publishing {listing_id}: {str(e)}")
            return {"success": False, "error": str(e), "listing_id": listing_id}
    
    async def update_listing(self, listing_id: str, update_data: dict) -> dict:
        """Update an existing listing"""
        try:
            print(f"✏️  Updating listing ID: {listing_id}")
            
            result = await self.client.update_listing(listing_id, update_data)
            
            print(f"✅ Successfully updated listing {listing_id}")
            return {"success": True, "response": result, "listing_id": listing_id}
            
        except Exception as e:
            print(f"❌ Error updating {listing_id}: {str(e)}")
            return {"success": False, "error": str(e), "listing_id": listing_id}
    
    async def verify_listing_status(self, listing_id: str, expected_action: str) -> bool:
        """Verify if an action was successful"""
        try:
            # Get current listing details
            listing = await self.client.get_listing(listing_id)
            current_state = listing.get('state', {}).get('slug', 'unknown')
            
            if expected_action == "end":
                if current_state == "ended":
                    print(f"✅ Verified: Listing {listing_id} is ended")
                    return True
                else:
                    print(f"⚠️  Listing {listing_id} state is '{current_state}', expected 'ended'")
                    return False
            
            elif expected_action == "publish":
                if current_state in ["live", "published"]:
                    print(f"✅ Verified: Listing {listing_id} is live")
                    return True
                else:
                    print(f"⚠️  Listing {listing_id} state is '{current_state}', expected 'live'")
                    return False
            
            return True  # For update operations, assume success if we can fetch it
            
        except Exception as e:
            print(f"❌ Error verifying {listing_id}: {str(e)}")
            return False
    
    async def process_listings(self, listing_ids: list, action: str, **kwargs) -> dict:
        """Process multiple Reverb listings"""
        results = {
            "total": len(listing_ids),
            "successful": 0,
            "failed": 0,
            "verified": 0,
            "details": []
        }
        
        verify = kwargs.get('verify', False)
        
        for listing_id in listing_ids:
            if action == "end":
                reason = kwargs.get('reason', 'not_sold')
                result = await self.end_listing(listing_id, reason)
            elif action == "publish":
                result = await self.publish_listing(listing_id)
            elif action == "update":
                update_data = kwargs.get('update_data', {})
                if update_data:
                    result = await self.update_listing(listing_id, update_data)
                else:
                    result = {"success": False, "error": "No update data provided", "listing_id": listing_id}
            else:
                result = {"success": False, "error": f"Unknown action: {action}", "listing_id": listing_id}
            
            is_successful = result.get("success", False)
            
            # If verification requested and action seemed successful, verify
            if verify and is_successful:
                await asyncio.sleep(2)  # Wait for Reverb to process
                if await self.verify_listing_status(listing_id, action):
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

def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(description='Manage Reverb listings via API')
    parser.add_argument('action', choices=['end', 'publish', 'update'], help='Action to perform')
    parser.add_argument('listing_ids', nargs='+', help='Reverb listing IDs to process')
    parser.add_argument('--api-key', help='Reverb API key (or set REVERB_API_KEY env var)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without actually doing it')
    parser.add_argument('--verify', action='store_true', help='Verify actions by checking listing status afterwards')
    
    # End-specific arguments
    parser.add_argument('--reason', choices=['not_sold', 'reverb_sale'], default='not_sold', 
                       help='Reason for ending listing (default: not_sold)')
    
    # Update-specific arguments
    parser.add_argument('--price', help='New price for update action')
    parser.add_argument('--description', help='New description for update action')
    parser.add_argument('--title', help='New title for update action')
    
    args = parser.parse_args()
    
    # Get API key
    api_key = args.api_key or os.environ.get('REVERB_API_KEY')
    
    if not api_key:
        print("❌ Error: Reverb API key required!")
        print("Provide via --api-key or set REVERB_API_KEY environment variable")
        sys.exit(1)
    
    if args.dry_run:
        action_text = {"end": "end", "publish": "publish", "update": "update"}[args.action]
        print(f"🔍 DRY RUN MODE - Would {action_text} these listings:")
        for listing_id in args.listing_ids:
            print(f"  - {listing_id}")
        if args.action == "end":
            print(f"  Reason: {args.reason}")
        print(f"Total: {len(args.listing_ids)} listings")
        return
    
    # Create manager
    manager = ReverbItemManager(api_key)
    
    async def run_operations():
        """Handle the main operations workflow"""
        
        # Prepare additional arguments
        kwargs = {'verify': args.verify}
        
        if args.action == "end":
            kwargs['reason'] = args.reason
        elif args.action == "update":
            # Prepare update data
            update_data = {}
            if args.price:
                # Reverb expects price in specific format
                update_data['price'] = {"amount": args.price, "currency": "USD"}
            if args.description:
                update_data['description'] = args.description
            if args.title:
                update_data['title'] = args.title
            
            if not update_data:
                print("❌ Error: No update data provided!")
                print("Use --price, --description, or --title to specify what to update")
                sys.exit(1)
            
            kwargs['update_data'] = update_data
            print(f"📝 Update data prepared: {update_data}")
        
        # Process listings
        action_text = {"end": "ending", "publish": "publishing", "update": "updating"}[args.action]
        action_past = {"end": "ENDED", "publish": "PUBLISHED", "update": "UPDATED"}[args.action]
        
        print(f"\n🔄 Starting {action_text} of {len(args.listing_ids)} listings...")
        
        if args.verify:
            print("🔍 Verification enabled - will check each listing after processing")
        
        try:
            results = await manager.process_listings(args.listing_ids, args.action, **kwargs)
        except Exception as e:
            print(f"❌ Critical error during {action_text}: {str(e)}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            sys.exit(1)
        
        # Print detailed summary (same as your V&R script)
        print(f"\n📊 **{action_past} SUMMARY**")
        print("=" * 50)
        print(f"Total listings processed: {results['total']}")
        print(f"✅ Successful: {results['successful']}")
        print(f"❌ Failed: {results['failed']}")
        
        if args.verify and 'verified' in results:
            print(f"🔍 Verified successful: {results['verified']}")
        
        # Show success details
        if results['successful'] > 0:
            print(f"\n✅ **SUCCESSFUL {action_past} OPERATIONS:**")
            for detail in results['details']:
                if detail.get('success', False):
                    listing_id = detail.get('listing_id', 'Unknown')
                    response_info = detail.get('response', 'No response info')
                    
                    if isinstance(response_info, dict):
                        response_info = f"State: {response_info.get('state', {}).get('slug', 'unknown')}"
                    
                    verification_status = ""
                    if args.verify and detail.get('verified') is not None:
                        verification_status = " ✓ Verified" if detail.get('verified') else " ⚠️ Not verified"
                    
                    print(f"  - {listing_id}: {response_info}{verification_status}")
        
        # Show failure details
        if results['failed'] > 0:
            print(f"\n❌ **FAILED {action_past} OPERATIONS:**")
            for detail in results['details']:
                if not detail.get('success', False):
                    listing_id = detail.get('listing_id', 'Unknown')
                    error_msg = detail.get('error', 'Unknown error')
                    
                    if len(str(error_msg)) > 100:
                        error_msg = f"{str(error_msg)[:100]}..."
                    
                    print(f"  - {listing_id}: {error_msg}")
        
        # Final status message
        if results['failed'] == 0:
            print(f"\n🎉 All {results['successful']} listings successfully {action_text}!")
        elif results['successful'] == 0:
            print(f"\n💥 All {results['failed']} {action_text} operations failed!")
        else:
            print(f"\n⚖️  Mixed results: {results['successful']} succeeded, {results['failed']} failed")
        
        return results

    asyncio.run(run_operations())

if __name__ == '__main__':
    main()