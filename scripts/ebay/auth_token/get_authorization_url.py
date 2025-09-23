#!/usr/bin/env python3
"""
Generate eBay authorization URL to get a new refresh token.
"""

from app.core.config import get_settings

def generate_auth_url():
    """Generate the eBay authorization URL"""

    # Get settings
    settings = get_settings()

    # Check if we're using sandbox or production
    sandbox = False  # Set to True for sandbox

    # Get credentials
    if sandbox:
        client_id = settings.EBAY_SANDBOX_CLIENT_ID
        ru_name = settings.EBAY_SANDBOX_RU_NAME
    else:
        client_id = settings.EBAY_CLIENT_ID
        ru_name = settings.EBAY_RU_NAME

    if not client_id or not ru_name:
        print("❌ Missing required credentials")
        return

    # Generate authorization URL
    auth_url = f"https://auth.{'sandbox.' if sandbox else ''}ebay.com/oauth2/authorize"
    auth_url += f"?client_id={client_id}"
    auth_url += f"&response_type=code"
    auth_url += f"&redirect_uri={ru_name}"
    auth_url += f"&scope=https://api.ebay.com/oauth/api_scope "
    auth_url += f"https://api.ebay.com/oauth/api_scope/sell.inventory "
    auth_url += f"https://api.ebay.com/oauth/api_scope/sell.marketing "
    auth_url += f"https://api.ebay.com/oauth/api_scope/sell.account "
    auth_url += f"https://api.ebay.com/oauth/api_scope/sell.fulfillment"

    print("=== eBay Authorization URL Generator ===")
    print()
    print("To generate a new refresh token:")
    print()
    print("1. Copy this URL and open it in your browser:")
    print()
    print(auth_url)
    print()
    print("2. Log in to eBay and approve all the permissions")
    print()
    print("3. After approval, you'll be redirected to a URL that looks like:")
    print("   https://your-redirect-url?code=v%5E1.1%23i%5E1%23f%5E0%23r%5E1...")
    print()
    print("4. Copy the ENTIRE redirect URL from your browser")
    print()
    print("5. Run: python scripts/ebay/auth_token/generate_token.py")
    print("   The script will prompt you to paste the redirect URL")
    print()
    print("6. The script will extract the code and generate a new refresh token")
    print("   Add the refresh token to your .env file as EBAY_REFRESH_TOKEN")

if __name__ == "__main__":
    generate_auth_url()