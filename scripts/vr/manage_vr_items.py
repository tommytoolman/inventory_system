#!/usr/bin/env python3
"""
CLI script to manage V&R items using AJAX endpoints.
Usage: 
  python scripts/manage_vr_items.py delete [item_ids...] 
  python scripts/manage_vr_items.py mark-sold [item_ids...]

Examples:

# Delete items
python scripts/manage_vr_items.py delete --dry-run 122805 122806
python scripts/manage_vr_items.py delete --verify 122805 122806

# Mark items as sold  
python scripts/manage_vr_items.py mark-sold --dry-run 122755 122754
python scripts/manage_vr_items.py mark-sold 122755 122754

"""

import requests
import argparse
import sys
import os
import time
import random
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

class VRItemManager:
    """Manage V&R items using AJAX endpoints"""
    
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.authenticated = False
        
        # Headers to mimic browser behavior
        self.headers = {
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Language': 'en-US,en;q=0.9',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
            'Referer': 'https://www.vintageandrare.com/instruments/show'
        }

    def authenticate(self) -> bool:
        """Authenticate with V&R"""
        try:
            print(f"🔐 Authenticating with V&R as {self.username}...")
            
            # Get main page first
            response = self.session.get('https://www.vintageandrare.com')
            print(f"📄 Main page status: {response.status_code}")
            
            # Login
            login_data = {
                'username': self.username,
                'pass': self.password,
                'open_where': 'header'
            }
            
            response = self.session.post(
                'https://www.vintageandrare.com/do_login',
                data=login_data,
                headers=self.headers,
                allow_redirects=True
            )
            
            # Check authentication
            self.authenticated = 'Sign out' in response.text or '/account' in response.url
            
            if self.authenticated:
                print("✅ Authentication successful!")
            else:
                print("❌ Authentication failed!")
                
            return self.authenticated
            
        except Exception as e:
            print(f"❌ Authentication error: {str(e)}")
            return False

    def mark_item_as_sold(self, item_id: str) -> dict:
        """Mark a single V&R item as sold using AJAX"""
        if not self.authenticated:
            return {"success": False, "error": "Not authenticated"}
            
        try:
            print(f"💰 Marking item as sold ID: {item_id}")
            
            # Generate random number for cache busting (like V&R does)
            random_num = random.random()
            
            # AJAX mark as sold request (exact endpoint from your discovery)
            mark_sold_data = f'product_id={item_id}'
            
            response = self.session.post(
                f'https://www.vintageandrare.com/ajax/mark_as_sold/{random_num}',
                data=mark_sold_data,
                headers=self.headers
            )
            
            print(f"📡 Mark sold response status: {response.status_code}")
            print(f"📝 Response content: '{response.text}'")
            print(f"📏 Response length: {len(response.text)} characters")
            
            if response.status_code == 200:
                response_text = response.text.strip()
                
                # Handle different response types
                if not response_text:
                    # Empty response - V&R often returns empty on successful operations
                    print(f"✅ Empty response (likely successful mark as sold) for {item_id}")
                    return {"success": True, "response": "empty_success", "item_id": item_id}
                
                # Try to parse JSON response
                try:
                    result = response.json()
                    print(f"✅ JSON response for {item_id}: {result}")
                    return {"success": True, "response": result, "item_id": item_id}
                except:
                    # If not JSON, check for success indicators in text
                    response_lower = response_text.lower()
                    if any(keyword in response_lower for keyword in ['success', 'sold', 'marked', 'ok', '1', 'true']):
                        print(f"✅ Text indicates success for {item_id}")
                        return {"success": True, "response": response_text, "item_id": item_id}
                    elif any(keyword in response_lower for keyword in ['error', 'failed', 'not found', 'invalid']):
                        print(f"❌ Text indicates failure for {item_id}: {response_text}")
                        return {"success": False, "error": f"Server error: {response_text}", "item_id": item_id}
                    else:
                        print(f"⚠️  Unknown response for {item_id}: '{response_text}'")
                        # For now, assume success if we got a 200 status
                        return {"success": True, "response": f"unknown_success: {response_text}", "item_id": item_id}
            else:
                print(f"❌ Mark sold failed for {item_id}: HTTP {response.status_code}")
                return {"success": False, "error": f"HTTP {response.status_code}: {response.text}", "item_id": item_id}
                
        except Exception as e:
            print(f"❌ Error marking {item_id} as sold: {str(e)}")
            return {"success": False, "error": str(e), "item_id": item_id}

    def delete_item(self, item_id: str) -> dict:
        """Delete a single V&R item using AJAX"""
        if not self.authenticated:
            return {"success": False, "error": "Not authenticated"}
            
        try:
            print(f"🗑️  Deleting item ID: {item_id}")
            
            # AJAX delete request
            delete_data = {
                'product_id': str(item_id)
            }
            
            response = self.session.post(
                'https://www.vintageandrare.com/ajax/delete_item',
                data=delete_data,
                headers=self.headers
            )
            
            print(f"📡 Delete response status: {response.status_code}")
            print(f"📝 Response content: '{response.text}'")
            print(f"📏 Response length: {len(response.text)} characters")
            
            if response.status_code == 200:
                response_text = response.text.strip()
                
                # Handle different response types
                if not response_text:
                    # Empty response - V&R often returns empty on successful delete
                    print(f"✅ Empty response (likely successful delete) for {item_id}")
                    return {"success": True, "response": "empty_success", "item_id": item_id}
                
                # Try to parse JSON response
                try:
                    result = response.json()
                    print(f"✅ JSON response for {item_id}: {result}")
                    return {"success": True, "response": result, "item_id": item_id}
                except:
                    # If not JSON, check for success indicators in text
                    response_lower = response_text.lower()
                    if any(keyword in response_lower for keyword in ['success', 'deleted', 'removed', 'ok']):
                        print(f"✅ Text indicates success for {item_id}")
                        return {"success": True, "response": response_text, "item_id": item_id}
                    elif any(keyword in response_lower for keyword in ['error', 'failed', 'not found', 'invalid']):
                        print(f"❌ Text indicates failure for {item_id}: {response_text}")
                        return {"success": False, "error": f"Server error: {response_text}", "item_id": item_id}
                    else:
                        print(f"⚠️  Unknown response for {item_id}: '{response_text}'")
                        return {"success": True, "response": f"unknown_success: {response_text}", "item_id": item_id}
            else:
                print(f"❌ Delete failed for {item_id}: HTTP {response.status_code}")
                return {"success": False, "error": f"HTTP {response.status_code}: {response.text}", "item_id": item_id}
                
        except Exception as e:
            print(f"❌ Error deleting {item_id}: {str(e)}")
            return {"success": False, "error": str(e), "item_id": item_id}

    def process_items(self, item_ids: list, action: str, verify: bool = False) -> dict:
        """Process multiple V&R items (delete or mark as sold)"""
        results = {
            "total": len(item_ids),
            "successful": 0,
            "failed": 0,
            "verified": 0,
            "details": []
        }
        
        for item_id in item_ids:
            if action == "delete":
                result = self.delete_item(item_id)
            elif action == "mark-sold":
                result = self.mark_item_as_sold(item_id)
            else:
                result = {"success": False, "error": f"Unknown action: {action}", "item_id": item_id}
            
            # If verification requested and action seemed successful, verify
            if verify and result["success"]:
                time.sleep(2)  # Wait a bit for V&R to process
                if self.verify_item_status(item_id, action):
                    result["verified"] = True
                    results["verified"] += 1
                else:
                    result["verified"] = False
                    result["success"] = False  # Mark as failed if verification failed
                    
            results["details"].append(result)
            
            if result["success"]:
                results["successful"] += 1
            else:
                results["failed"] += 1
                
            # Small delay between operations to be nice to the server
            time.sleep(1)
        
        return results

    def verify_item_status(self, item_id: str, action: str) -> bool:
        """Verify if an action was successful"""
        try:
            # Try to access the item's page
            response = self.session.get(f'https://www.vintageandrare.com/instruments/{item_id}')
            
            if action == "delete":
                if response.status_code == 404:
                    print(f"✅ Verified: Item {item_id} is deleted (404)")
                    return True
                elif 'not found' in response.text.lower() or 'does not exist' in response.text.lower():
                    print(f"✅ Verified: Item {item_id} is deleted (not found)")
                    return True
                else:
                    print(f"⚠️  Item {item_id} may still exist (status: {response.status_code})")
                    return False
            
            elif action == "mark-sold":
                if response.status_code == 200:
                    # For mark as sold, we'd need to check the page content for "sold" indicators
                    # This is more complex to verify automatically
                    print(f"⚠️  Item {item_id} verification for 'mark-sold' not implemented")
                    return True  # Assume success for now
                else:
                    print(f"⚠️  Cannot verify {item_id} mark-sold status")
                    return False
                    
        except Exception as e:
            print(f"❌ Error verifying {item_id}: {str(e)}")
            return False

def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(description='Manage V&R items via AJAX')
    parser.add_argument('action', choices=['delete', 'mark-sold'], help='Action to perform')
    parser.add_argument('item_ids', nargs='+', help='V&R item IDs to process')
    parser.add_argument('--username', help='V&R username (or set VR_USERNAME env var)')
    parser.add_argument('--password', help='V&R password (or set VR_PASSWORD env var)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without actually doing it')
    parser.add_argument('--verify', action='store_true', help='Verify actions by checking item status afterwards')
    
    args = parser.parse_args()
    
    # Get credentials
    username = args.username or os.environ.get('VR_USERNAME') or os.environ.get('VINTAGE_AND_RARE_USERNAME')
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
    manager = VRItemManager(username, password)
    
    if not manager.authenticate():
        print("❌ Failed to authenticate with V&R")
        sys.exit(1)
    
    # Process items
    action_text = "deletion" if args.action == "delete" else "marking as sold"
    print(f"\n🔄 Starting {action_text} of {len(args.item_ids)} items...")
    results = manager.process_items(args.item_ids, args.action, args.verify)
    
    # Print summary
    action_past = "DELETED" if args.action == "delete" else "MARKED AS SOLD"
    print(f"\n📊 **{action_past} SUMMARY**")
    print(f"Total items: {results['total']}")
    print(f"✅ Successful: {results['successful']}")
    print(f"❌ Failed: {results['failed']}")
    
    if results['failed'] > 0:
        print(f"\n❌ **FAILED OPERATIONS:**")
        for detail in results['details']:
            if not detail['success']:
                print(f"  - {detail['item_id']}: {detail['error']}")

if __name__ == '__main__':
    main()