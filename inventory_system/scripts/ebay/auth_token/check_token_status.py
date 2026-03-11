#!/usr/bin/env python3
"""
Check eBay token status and generate authorization URL if needed.

Since we moved to Railway deployment, tokens are stored differently:
- Refresh token: Stored in environment variable EBAY_REFRESH_TOKEN
- Access token: Stored in memory only (not persisted)
"""

import os
import asyncio
from app.services.ebay.auth import EbayAuthManager
from app.core.config import get_settings

async def check_token_status():
    """Check the current eBay token status"""

    # Check if we're using sandbox or production
    sandbox = False  # Set to True for sandbox

    # Get settings
    settings = get_settings()

    # Check if refresh token exists in environment
    env_prefix = "EBAY_SANDBOX_" if sandbox else "EBAY_"
    refresh_token = os.getenv(f"{env_prefix}REFRESH_TOKEN")

    print(f"=== eBay Token Status Check ===")
    print(f"Mode: {'Sandbox' if sandbox else 'Production'}")
    print()

    if refresh_token:
        print(f"✅ Refresh token found in environment variable")
        print(f"   Token (first 20 chars): {refresh_token[:20]}...")
        print()

        # Try to initialize auth manager and get access token
        try:
            auth_manager = EbayAuthManager(sandbox=sandbox)

            # Check if we can get a valid access token
            access_token = await auth_manager.get_access_token()

            if access_token:
                print(f"✅ Valid access token in memory")
                print(f"   Access token (first 20 chars): {access_token[:20]}...")
            else:
                print(f"⚠️  No valid access token in memory")
                print(f"   Will be fetched on next API call")

        except Exception as e:
            print(f"❌ Error: {str(e)}")
            print()

            # If refresh token is invalid, generate new auth URL
            if "Invalid refresh token" in str(e) or "invalid_grant" in str(e):
                print("🔄 Your refresh token has expired. Let's generate a new one...")
                print()
                generate_auth_url_instructions(settings, sandbox)

    else:
        print(f"❌ No refresh token found in environment variable {env_prefix}REFRESH_TOKEN")
        print()
        generate_auth_url_instructions(settings, sandbox)

    # Show current environment info
    print()
    print("=== Current Environment ===")
    print(f"Client ID: {'✅ Set' if getattr(settings, f'EBAY{"_SANDBOX" if sandbox else ""}_CLIENT_ID', None) else '❌ Not set'}")
    print(f"Client Secret: {'✅ Set' if getattr(settings, f'EBAY{"_SANDBOX" if sandbox else ""}_CLIENT_SECRET', None) else '❌ Not set'}")
    print(f"RU Name: {'✅ Set' if getattr(settings, f'EBAY{"_SANDBOX" if sandbox else ""}_RU_NAME', None) else '❌ Not set'}")
    print(f"Dev ID: {'✅ Set' if getattr(settings, f'EBAY{"_SANDBOX" if sandbox else ""}_DEV_ID', None) else '❌ Not set'}")


def generate_auth_url_instructions(settings, sandbox):
    """Generate and display authorization URL instructions"""

    # Check required credentials
    client_id = getattr(settings, f"EBAY{'' if not sandbox else '_SANDBOX'}_CLIENT_ID", None)
    client_secret = getattr(settings, f"EBAY{'' if not sandbox else '_SANDBOX'}_CLIENT_SECRET", None)
    ru_name = getattr(settings, f"EBAY{'' if not sandbox else '_SANDBOX'}_RU_NAME", None)

    if not all([client_id, client_secret, ru_name]):
        print("❌ Missing required eBay credentials in environment")
        print("   Please ensure the following are set:")
        env_prefix = "EBAY_SANDBOX_" if sandbox else "EBAY_"
        if not client_id:
            print(f"   - {env_prefix}CLIENT_ID")
        if not client_secret:
            print(f"   - {env_prefix}CLIENT_SECRET")
        if not ru_name:
            print(f"   - {env_prefix}RU_NAME")
        return

    try:
        # Create a temporary auth manager without requiring refresh token
        # We'll temporarily bypass the token manager initialization
        temp_auth_manager = type('TempAuthManager', (), {
            'client_id': client_id,
            'ru_name': ru_name,
            'auth_url': f"https://auth.{'sandbox.' if sandbox else ''}ebay.com/oauth2/authorize",
            'scopes': ["https://api.ebay.com/oauth/api_scope/sell.inventory"],
            'get_authorization_url': lambda self: (
                f"{self.auth_url}"
                f"?client_id={self.client_id}"
                f"&redirect_uri={self.ru_name}"
                f"&response_type=code"
                f"&scope={('%20'.join(self.scopes))}"
            )
        })()

        auth_url = temp_auth_manager.get_authorization_url()

        print("To generate a new refresh token:")
        print(f"1. Go to this URL in your browser:")
        print(f"   {auth_url}")
        print()
        print("2. Log in to eBay and approve the permissions")
        print()
        print("3. After approval, you'll be redirected to a URL with a code parameter")
        print("   Copy the entire URL from your browser")
        print()
        print("4. Run the generate_token.py script with the URL:")
        print(f"   python scripts/ebay/auth_token/generate_token.py")
        print()
        print("5. The script will extract the code and generate a refresh token")
        print("   Update your .env file with the new EBAY_REFRESH_TOKEN")

    except Exception as e:
        print(f"❌ Error generating authorization URL: {str(e)}")


if __name__ == "__main__":
    asyncio.run(check_token_status())