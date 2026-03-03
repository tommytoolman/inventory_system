#!/usr/bin/env python3
"""
WooCommerce API Connection Debugger
This script tests various authentication methods and diagnoses connection issues
"""

import requests
from requests.auth import HTTPBasicAuth
import json

# Your credentials
STORE_URL = "https://obtainable-peccary-db20dc.instawp.site"
CONSUMER_KEY = "ck_8828717bc3e769b75660cfe79d1453a737cf0e6f"
CONSUMER_SECRET = "cs_5754346a7d35bf57a453e0c753f0dfd72c4b273b"

def print_section(title):
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60)

def test_wordpress_api():
    """Test if WordPress REST API is accessible"""
    print_section("Test 1: WordPress REST API")
    
    url = f"{STORE_URL}/wp-json/"
    try:
        response = requests.get(url, timeout=5)
        print(f"✅ WordPress REST API accessible")
        print(f"Status: {response.status_code}")
        data = response.json()
        print(f"WordPress Version: {data.get('description', 'Unknown')}")
        return True
    except Exception as e:
        print(f"❌ Cannot access WordPress REST API")
        print(f"Error: {str(e)}")
        return False

def test_woocommerce_api_info():
    """Check if WooCommerce API is available"""
    print_section("Test 2: WooCommerce API Availability")
    
    url = f"{STORE_URL}/wp-json/wc/v3"
    try:
        response = requests.get(url, timeout=5)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 401:
            print("✅ WooCommerce API exists (401 means it's there, just needs auth)")
            return True
        elif response.status_code == 200:
            print("✅ WooCommerce API accessible")
            return True
        else:
            print(f"⚠️  Unexpected status: {response.status_code}")
            print(response.text)
            return False
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

def test_basic_auth_header():
    """Test with Basic Auth in header"""
    print_section("Test 3: Basic Auth (Header)")
    
    url = f"{STORE_URL}/wp-json/wc/v3/products"
    try:
        response = requests.get(
            url,
            auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET),
            timeout=10
        )
        
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            print("✅ SUCCESS! Basic Auth header works!")
            products = response.json()
            print(f"Found {len(products)} products")
            return True
        else:
            print(f"❌ Failed: {response.status_code}")
            print(f"Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

def test_query_string_auth():
    """Test with credentials in query string"""
    print_section("Test 4: Query String Auth")
    
    url = f"{STORE_URL}/wp-json/wc/v3/products"
    params = {
        'consumer_key': CONSUMER_KEY,
        'consumer_secret': CONSUMER_SECRET
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            print("✅ SUCCESS! Query string auth works!")
            products = response.json()
            print(f"Found {len(products)} products")
            return True
        else:
            print(f"❌ Failed: {response.status_code}")
            print(f"Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

def test_system_status():
    """Try to access system status endpoint (requires auth)"""
    print_section("Test 5: System Status (Requires Auth)")
    
    url = f"{STORE_URL}/wp-json/wc/v3/system_status"
    
    # Try with query string
    params = {
        'consumer_key': CONSUMER_KEY,
        'consumer_secret': CONSUMER_SECRET
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            print("✅ Can access authenticated endpoints")
            return True
        else:
            print(f"❌ Cannot access authenticated endpoints")
            print(f"Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

def check_user_permissions():
    """Provide guidance on checking user permissions"""
    print_section("Manual Check Required: User Permissions")
    print("""
Please verify in WordPress admin:

1. Go to: WooCommerce → Settings → Advanced → REST API
2. Find your "RIFF Integration" key
3. Check the "User" column - should show your admin username
4. Check "Permissions" column - should show "Read/Write"

If it shows a different user or "Read" only:
- Delete the key
- Create a new one with the admin user and Read/Write permissions
    """)

def suggest_fixes():
    """Suggest possible fixes based on common issues"""
    print_section("Possible Fixes to Try")
    print("""
Fix 1: Recreate API Keys with Correct User
------------------------------------------
1. Go to WooCommerce → Settings → Advanced → REST API
2. Delete existing "RIFF Integration" key
3. Click "Add key"
4. Description: RIFF Integration
5. User: SELECT THE ADMIN USER (the one you log in with)
6. Permissions: Read/Write
7. Generate API Key
8. Copy BOTH keys
9. Run this script again with new keys

Fix 2: Check WordPress User Roles
----------------------------------
1. Go to Users → All Users
2. Find your admin user
3. Make sure Role is "Administrator"
4. If not, change it to Administrator

Fix 3: Disable Plugin Conflicts
--------------------------------
Try temporarily disabling other plugins:
1. Go to Plugins → Installed Plugins
2. Deactivate all plugins EXCEPT WooCommerce
3. Try the API again
4. If it works, reactivate plugins one by one to find the conflict

Fix 4: Check .htaccess (if applicable)
---------------------------------------
Some hosting adds security rules that block API access.
Not applicable to Docker, but good to know for production.

Fix 5: Fresh WooCommerce Installation
--------------------------------------
If all else fails, we can rebuild the Docker setup from scratch.
    """)

def main():
    print("""
╔════════════════════════════════════════════════════════════════╗
║         WooCommerce API Connection Debugger                    ║
║                                                                ║
║  This script will test your WooCommerce API connection        ║
║  and help diagnose any authentication issues.                 ║
╚════════════════════════════════════════════════════════════════╝
    """)
    
    print(f"\nTesting connection to: {STORE_URL}")
    print(f"Consumer Key: {CONSUMER_KEY[:20]}...")
    print(f"Consumer Secret: {CONSUMER_SECRET[:20]}...")
    
    results = []
    
    # Run all tests
    results.append(("WordPress API", test_wordpress_api()))
    results.append(("WooCommerce API", test_woocommerce_api_info()))
    results.append(("Basic Auth Header", test_basic_auth_header()))
    results.append(("Query String Auth", test_query_string_auth()))
    results.append(("System Status", test_system_status()))
    
    # Summary
    print_section("TEST RESULTS SUMMARY")
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name:.<40} {status}")
    
    # If nothing worked
    if not any(result[1] for result in results[2:]):  # Skip first 2 basic tests
        print("\n❌ All authentication tests failed!")
        check_user_permissions()
        suggest_fixes()
    else:
        print("\n✅ At least one authentication method works!")
        print("You can proceed with the integration.")
    
    print("\n" + "="*60)
    print("Diagnostic complete!")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()