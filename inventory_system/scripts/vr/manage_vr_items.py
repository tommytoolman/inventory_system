#!/usr/bin/env python3
"""
CLI script to manage V&R items using AJAX endpoints.
Usage:
    python scripts/vr/manage_vr_items.py delete [item_ids...]
    python scripts/vr/manage_vr_items.py mark-sold [item_ids...]
    python scripts/vr/manage_vr_items.py restore [item_id]

Examples:

# Delete items
    python scripts/vr/manage_vr_items.py delete --dry-run 122805 122806
    python scripts/vr/manage_vr_items.py delete --verify 122805 122806

# Mark items as sold
    python scripts/vr/manage_vr_items.py mark-sold --dry-run 122755 122754
    python scripts/vr/manage_vr_items.py mark-sold 122755 122754

# Restore sold item back to active
    python scripts/vr/manage_vr_items.py restore 57543

"""

import argparse
import sys
import os

from pathlib import Path
from dotenv import load_dotenv

# Add the project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables from .env file
load_dotenv(project_root / '.env')  # Add this line

from app.services.vintageandrare.client import VintageAndRareClient


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(description='Manage V&R items via AJAX')
    parser.add_argument('action', choices=['delete', 'mark-sold', 'restore', 'edit', 'debug-mark', 'test-variations'], help='Action to perform')
    parser.add_argument('item_ids', nargs='+', help='V&R item IDs to process')
    parser.add_argument('--username', help='V&R username (or set VR_USERNAME env var)')
    parser.add_argument('--password', help='V&R password (or set VR_PASSWORD env var)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without actually doing it')
    parser.add_argument('--verify', action='store_true', help='Verify actions by checking item status afterwards')
    
    # Add edit-specific arguments:
    parser.add_argument('--description', help='New description for edit action')
    parser.add_argument('--price', help='New price for edit action')
    parser.add_argument('--title', help='New title/model for edit action')
    
    args = parser.parse_args()
    
    # Get credentials
    username = os.environ.get('VINTAGE_AND_RARE_USERNAME') or args.username or os.environ.get('VR_USERNAME')
    password = args.password or os.environ.get('VR_PASSWORD') or os.environ.get('VINTAGE_AND_RARE_PASSWORD')
    
    if not username or password is None:
        print("❌ Error: V&R credentials required!")
        print("Provide via --username/--password or set VR_USERNAME/VR_PASSWORD environment variables")
        sys.exit(1)
    
    if args.dry_run:
        action_text = "delete" if args.action == "delete" else "mark as sold"
        print(f"🔍 DRY RUN MODE - Would {action_text} these items:")
        for item_id in args.item_ids:
            print(f"  - {item_id}")
        print(f"Total: {len(args.item_ids)} items")
        return
    
    # Create manager and authenticate
    # manager = VRItemManager(username, password)
    # if not manager.authenticate():
        print("❌ Failed to authenticate with V&R")
        sys.exit(1)
    
    # Use the client instead of VRItemManager
    client = VintageAndRareClient(username=username, password=password)
    
    # Authenticate (now async, so we need to handle that)
    import asyncio
    
    async def run_operations():
        """Handle the main operations workflow with improved error handling and debug options"""

        # Authentication
        try:
            if not await client.authenticate():
                print("❌ Failed to authenticate with V&R")
                print("Please check your credentials and try again.")
                sys.exit(1)
            print("✅ Authentication successful")
        except Exception as e:
            print(f"❌ Authentication error: {str(e)}")
            sys.exit(1)

        # Handle debug actions (single item only)
        if args.action in ['debug-mark', 'test-variations', 'restore']:
            if len(args.item_ids) > 1:
                print(f"⚠️  {args.action} mode only supports one item at a time")
                print(f"Using first item: {args.item_ids[0]}")

            item_id = args.item_ids[0]

            if args.action == 'debug-mark':
                print(f"\n🔍 **DEBUG MARK-AS-SOLD FOR ITEM {item_id}**")
                result = await client.debug_mark_as_sold(item_id)
                print(f"\n📊 **DEBUG RESULTS:**")
                print(f"Status Code: {result.get('status_code')}")
                print(f"Response Text: '{result.get('response_text')}'")
                print(f"Content Length: {len(result.get('response_text', ''))}")

            elif args.action == 'test-variations':
                print(f"\n🧪 **TESTING MARK-AS-SOLD VARIATIONS FOR ITEM {item_id}**")
                result = await client.test_mark_as_sold_variations(item_id)
                print(f"\n📊 **TEST RESULTS:**")
                for i, (method, status, text) in enumerate(result.get('tests', []), 1):
                    print(f"Test {i} ({method}): HTTP {status} - '{text}'")

            elif args.action == 'restore':
                print(f"\n🔄 **RESTORING ITEM {item_id} FROM SOLD**")
                import random
                random_num = random.random()
                url = f'https://www.vintageandrare.com/ajax/restore_from_sold/{random_num}'

                ajax_headers = {
                    **client.headers,
                    'X-Requested-With': 'XMLHttpRequest',
                    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'Referer': 'https://www.vintageandrare.com/account/items',
                }

                restore_data = f'product_id={item_id}'

                session = client.cf_session if client.cf_session else client.session
                response = session.post(url, data=restore_data, headers=ajax_headers)

                print(f"\n📊 **RESTORE RESULTS:**")
                print(f"Status Code: {response.status_code}")
                print(f"Response Text: '{response.text}'")

                # Parse V&R response format: "Err::message" or success
                if response.status_code == 200:
                    if response.text.startswith('Err::'):
                        error_msg = response.text.split('::', 1)[1] if '::' in response.text else response.text
                        print(f"❌ V&R Error: {error_msg}")
                    else:
                        print(f"✅ Item {item_id} restored successfully!")
                else:
                    print(f"❌ HTTP Error: {response.status_code}")

            return  # Exit after debug operations
        
        # ✅ ADD: Prepare update_data for edit operations
        update_data = None
        if args.action == "edit":
            # Prepare update data from command line arguments
            update_data = {}
            
            if hasattr(args, 'description') and args.description:
                update_data['description'] = args.description
            if hasattr(args, 'price') and args.price:
                update_data['price'] = args.price
            if hasattr(args, 'title') and args.title:
                update_data['model'] = args.title  # Map title to model field
            
            # Check if any update data was provided
            if not update_data:
                print("❌ Error: No update data provided for edit operation!")
                print("Use --description, --price, or --title to specify what to update")
                sys.exit(1)
            
            print(f"📝 Update data prepared: {update_data}")        
        

        # Regular operations (delete or mark-sold)
        action_text = "deletion" if args.action == "delete" else ("editing" if args.action == "edit" else "marking as sold")
        action_past = "DELETED" if args.action == "delete" else ("EDITED" if args.action == "edit" else "MARKED AS SOLD")
        
        print(f"\n🔄 Starting {action_text} of {len(args.item_ids)} items...")
        
        # Show verification notice
        if args.verify:
            print("🔍 Verification enabled - will check each item after processing")
        
        # Process items
        try:
            results = await client.process_items(args.item_ids, args.action, args.verify, update_data)
        except Exception as e:
            print(f"❌ Critical error during {action_text}: {str(e)}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            sys.exit(1)
        
        # Print detailed summary
        print(f"\n📊 **{action_past} SUMMARY**")
        print("=" * 50)
        print(f"Total items processed: {results['total']}")
        print(f"✅ Successful: {results['successful']}")
        print(f"❌ Failed: {results['failed']}")
        
        # Show verification results if applicable
        if args.verify and 'verified' in results:
            print(f"🔍 Verified successful: {results['verified']}")
        
        # Show success details for successful operations
        if results['successful'] > 0:
            print(f"\n✅ **SUCCESSFUL {action_past} OPERATIONS:**")
            for detail in results['details']:
                if detail.get('success', False):
                    item_id = detail.get('item_id', 'Unknown')
                    response_info = detail.get('response', 'No response info')
                    
                    # Format response info nicely
                    if isinstance(response_info, dict):
                        response_info = f"JSON: {response_info}"
                    elif isinstance(response_info, str) and len(response_info) > 50:
                        response_info = f"'{response_info[:50]}...'"
                    else:
                        response_info = f"'{response_info}'"
                    
                    verification_status = ""
                    if args.verify and detail.get('verified') is not None:
                        verification_status = " ✓ Verified" if detail.get('verified') else " ⚠️ Not verified"
                    
                    print(f"  - {item_id}: {response_info}{verification_status}")
        
        # Show failure details for failed operations
        if results['failed'] > 0:
            print(f"\n❌ **FAILED {action_past} OPERATIONS:**")
            for detail in results['details']:
                if not detail.get('success', False):
                    item_id = detail.get('item_id', 'Unknown')
                    
                    # Extract error message from various possible keys
                    error_msg = (
                        detail.get('error') or 
                        detail.get('response') or 
                        detail.get('message') or
                        'Unknown error'
                    )
                    
                    # Handle complex error objects
                    if isinstance(error_msg, dict):
                        error_msg = error_msg.get('message', str(error_msg))
                    elif isinstance(error_msg, bool):
                        error_msg = f"Operation returned: {error_msg}"
                    
                    # Truncate very long error messages
                    if isinstance(error_msg, str) and len(error_msg) > 100:
                        error_msg = f"{error_msg[:100]}..."
                    
                    print(f"  - {item_id}: {error_msg}")
        
        # Final status message
        if results['failed'] == 0:
            print(f"\n🎉 All {results['successful']} items successfully {action_text.replace('ion', 'ed')}!")
        elif results['successful'] == 0:
            print(f"\n💥 All {results['failed']} {action_text} operations failed!")
        else:
            print(f"\n⚖️  Mixed results: {results['successful']} succeeded, {results['failed']} failed")
        
        return results

        # if not await client.authenticate():
        #     print("❌ Failed to authenticate with V&R")
        #     sys.exit(1)    

        # # Process items
        # action_text = "deletion" if args.action == "delete" else "marking as sold"
        # print(f"\n🔄 Starting {action_text} of {len(args.item_ids)} items...")
        # # results = manager.process_items(args.item_ids, args.action, args.verify)
        # results = await client.process_items(args.item_ids, args.action, args.verify)
        
        # # Print summary
        # action_past = "DELETED" if args.action == "delete" else "MARKED AS SOLD"
        # print(f"\n📊 **{action_past} SUMMARY**")
        # print(f"Total items: {results['total']}")
        # print(f"✅ Successful: {results['successful']}")
        # print(f"❌ Failed: {results['failed']}")
        
        # if results['failed'] > 0:
        #     print(f"\n❌ **FAILED OPERATIONS:**")
        #     for detail in results['details']:
        #         if not detail['success']:
        #             # ✅ FIX: Handle both 'error' and 'response' keys
        #             error_msg = detail.get('error') or detail.get('response') or 'Unknown error'
        #             print(f"  - {detail['item_id']}: {error_msg}")

    asyncio.run(run_operations())

if __name__ == '__main__':
    main()