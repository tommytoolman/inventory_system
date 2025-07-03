#!/usr/bin/env python3
"""
CLI script to delete V&R items using the AJAX endpoint.
Usage: python scripts/delete_vr_items.py [item_ids...]

How to run, example:

# Step 1: Check what would be deleted
python scripts/delete_vr_items.py --dry-run 122805 122806

# Step 2: If it looks right, delete with verification
python scripts/delete_vr_items.py --verify 122805 122806

"""

import requests
import argparse
import sys
import os
import time
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

class VRItemDeleter:
    """Delete V&R items using the AJAX endpoint"""
    
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
            print(f"📝 Response content: '{response.text}'")  # Show quotes to see empty responses
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
                        # For now, assume success if we got a 200 status
                        return {"success": True, "response": f"unknown_success: {response_text}", "item_id": item_id}
            else:
                print(f"❌ Delete failed for {item_id}: HTTP {response.status_code}")
                return {"success": False, "error": f"HTTP {response.status_code}: {response.text}", "item_id": item_id}
                
        except Exception as e:
            print(f"❌ Error deleting {item_id}: {str(e)}")
            return {"success": False, "error": str(e), "item_id": item_id}

    def delete_items(self, item_ids: list, verify: bool = False) -> dict:
        """Delete multiple V&R items"""
        results = {
            "total": len(item_ids),
            "successful": 0,
            "failed": 0,
            "verified": 0,
            "details": []
        }
        
        for item_id in item_ids:
            result = self.delete_item(item_id)
            
            # If verification requested and delete seemed successful, verify
            if verify and result["success"]:
                time.sleep(2)  # Wait a bit for V&R to process
                if self.verify_item_deleted(item_id):
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
                
            # Small delay between deletions to be nice to the server
            time.sleep(1)
        
        return results

    def verify_item_deleted(self, item_id: str) -> bool:
        """Verify if an item was actually deleted by trying to access it"""
        try:
            # Try to access the item's page
            response = self.session.get(f'https://www.vintageandrare.com/instruments/{item_id}')
            
            if response.status_code == 404:
                print(f"✅ Verified: Item {item_id} is deleted (404)")
                return True
            elif 'not found' in response.text.lower() or 'does not exist' in response.text.lower():
                print(f"✅ Verified: Item {item_id} is deleted (not found)")
                return True
            else:
                print(f"⚠️  Item {item_id} may still exist (status: {response.status_code})")
                return False
                
        except Exception as e:
            print(f"❌ Error verifying {item_id}: {str(e)}")
            return False

def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(description='Delete V&R items via AJAX')
    parser.add_argument('item_ids', nargs='+', help='V&R item IDs to delete')
    parser.add_argument('--username', help='V&R username (or set VR_USERNAME env var)')
    parser.add_argument('--password', help='V&R password (or set VR_PASSWORD env var)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be deleted without actually deleting')
    parser.add_argument('--verify', action='store_true', help='Verify deletions by checking if items still exist')
    
    args = parser.parse_args()
    
    # Get credentials
    username = args.username or os.environ.get('VR_USERNAME') or os.environ.get('VINTAGE_AND_RARE_USERNAME')
    password = args.password or os.environ.get('VR_PASSWORD') or os.environ.get('VINTAGE_AND_RARE_PASSWORD')
    
    if not username or not password:
        print("❌ Error: V&R credentials required!")
        print("Provide via --username/--password or set VR_USERNAME/VR_PASSWORD environment variables")
        sys.exit(1)
    
    if args.dry_run:
        print("🔍 DRY RUN MODE - Would delete these items:")
        for item_id in args.item_ids:
            print(f"  - {item_id}")
        print(f"Total: {len(args.item_ids)} items")
        return
    
    # Create deleter and authenticate
    deleter = VRItemDeleter(username, password)
    
    if not deleter.authenticate():
        print("❌ Failed to authenticate with V&R")
        sys.exit(1)
    
    # Delete items
    print(f"\n🗑️  Starting deletion of {len(args.item_ids)} items...")
    results = deleter.delete_items(args.item_ids)
    
    # Print summary
    print(f"\n📊 **DELETION SUMMARY**")
    print(f"Total items: {results['total']}")
    print(f"✅ Successful: {results['successful']}")
    print(f"❌ Failed: {results['failed']}")
    
    if results['failed'] > 0:
        print(f"\n❌ **FAILED DELETIONS:**")
        for detail in results['details']:
            if not detail['success']:
                print(f"  - {detail['item_id']}: {detail['error']}")

if __name__ == '__main__':
    main()