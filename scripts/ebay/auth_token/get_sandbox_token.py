#!/usr/bin/env python3
"""
Quick script to get a new eBay Sandbox token
"""

import asyncio
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent.parent))

from app.services.ebay.auth import EbayAuthManager

async def main():
    print("\n🏖️  eBay SANDBOX Token Generator")
    print("="*50)
    
    auth_manager = EbayAuthManager(sandbox=True)
    
    # Step 1: Generate authorization URL
    print("\n📝 Step 1: Get Authorization URL")
    auth_url = auth_manager.get_authorization_url()
    
    print("\n🔗 Open this URL in your browser:")
    print(f"\n{auth_url}\n")
    
    print("📋 Instructions:")
    print("1. Log into your eBay SANDBOX account")
    print("2. Review and ACCEPT the permissions")
    print("3. You'll be redirected to a URL")
    print("4. Copy the ENTIRE URL from your browser address bar")
    
    # Step 2: Get the redirect URL from user
    print("\n" + "="*50)
    redirect_url = input("Paste the ENTIRE redirect URL here and press Enter:\n> ").strip()
    
    if not redirect_url:
        print("❌ No URL provided!")
        return
    
    # Step 3: Extract authorization code
    try:
        parsed_url = urlparse(redirect_url)
        query_params = parse_qs(parsed_url.query)
        auth_code = query_params.get('code', [None])[0]
        
        if not auth_code:
            print("❌ No authorization code found in URL!")
            print("   Make sure you copied the entire URL including ?code=...")
            return
            
        print("✅ Authorization code extracted!")
        
    except Exception as e:
        print(f"❌ Error parsing URL: {e}")
        return
    
    # Step 4: Exchange for tokens
    print("\n🔄 Exchanging code for tokens...")
    try:
        refresh_token = await auth_manager.generate_refresh_token(auth_code)
        
        if refresh_token:
            print("\n✅ SUCCESS! Refresh token generated")
            print(f"   Preview: {refresh_token[:30]}...")
            
            # Test access token
            print("\n🔄 Getting access token...")
            access_token = await auth_manager.get_access_token()
            print(f"✅ Access token obtained!")
            print(f"   Preview: {access_token[:30]}...")
            
            print("\n🎉 SANDBOX TOKENS READY!")
            print("📁 Saved to: ebay_sandbox_tokens.json")
            print("\n✅ You can now create eBay listings in sandbox mode!")
            
        else:
            print("❌ Failed to generate tokens")
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())