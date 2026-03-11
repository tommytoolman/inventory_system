#!/usr/bin/env python3
"""
Exchange authorization code for sandbox tokens
Securely prompts for the redirect URL
"""

import asyncio
import sys
import getpass
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent.parent))

from app.services.ebay.auth import EbayAuthManager

async def main():
    print("\n🏖️  eBay SANDBOX Token Exchange")
    print("="*50)
    
    # Securely get URL via prompt (won't show in command history)
    print("\n📋 Instructions:")
    print("1. Make sure you've authorized in your browser")
    print("2. Copy the ENTIRE redirect URL from your browser")
    print("3. Paste it below (it will be hidden for security)")
    print("\nNote: The URL starts with your redirect URI and contains ?code=...")
    
    try:
        # Use getpass for secure input (hides the URL as you type)
        redirect_url = getpass.getpass("\n🔒 Paste redirect URL (hidden): ").strip()
    except KeyboardInterrupt:
        print("\n\n❌ Cancelled")
        return
    
    if not redirect_url:
        print("\n❌ ERROR: No URL provided")
        return
    
    # Extract authorization code from URL
    try:
        parsed_url = urlparse(redirect_url)
        query_params = parse_qs(parsed_url.query)
        auth_code = query_params.get('code', [None])[0]
        
        if not auth_code:
            print("\n❌ ERROR: No authorization code found in URL!")
            print("   Make sure you copied the ENTIRE URL including ?code=...")
            print(f"\n   URL provided: {redirect_url[:100]}...")
            return
            
        print(f"✅ Authorization code extracted successfully!")
        print(f"   Code preview: {auth_code[:30]}...")
        
    except Exception as e:
        print(f"\n❌ Error parsing URL: {e}")
        return
    
    # Initialize auth manager for sandbox
    auth_manager = EbayAuthManager(sandbox=True)
    
    # Exchange code for tokens
    print("\n🔄 Exchanging authorization code for tokens...")
    try:
        refresh_token = await auth_manager.generate_refresh_token(auth_code)
        
        if refresh_token:
            print("\n✅ SUCCESS! Refresh token generated")
            print(f"   Refresh token preview: {refresh_token[:40]}...")
            
            # Get access token to verify everything works
            print("\n🔄 Testing by getting access token...")
            access_token = await auth_manager.get_access_token()
            print(f"✅ Access token obtained successfully!")
            print(f"   Access token preview: {access_token[:40]}...")
            
            # Check expiry info
            valid, days_left, access_valid, minutes_left = auth_manager.token_storage.get_token_expiry_info()
            
            print("\n📊 Token Status:")
            print(f"   Refresh Token: Valid for {days_left} days")
            print(f"   Access Token: Valid for {minutes_left} minutes")
            
            print("\n🎉 SANDBOX TOKENS READY!")
            print("📁 Tokens saved to: app/services/ebay/tokens/ebay_sandbox_tokens.json")
            print("\n✅ You can now create eBay listings in sandbox mode!")
            print("   Use: python scripts/process_sync_event.py --event-id X --platforms ebay --sandbox")
            
        else:
            print("\n❌ Failed to generate refresh token")
            print("   The authorization code may have expired (5 minute limit)")
            print("   Please generate a new authorization URL and try again")
            
    except Exception as e:
        print(f"\n❌ Error exchanging code: {str(e)}")
        print("\nPossible causes:")
        print("- Authorization code expired (5 minute limit)")
        print("- Code already used (can only be used once)")
        print("- Wrong environment (using production code for sandbox)")

if __name__ == "__main__":
    asyncio.run(main())