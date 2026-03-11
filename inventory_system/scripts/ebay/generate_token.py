# scripts/ebay/generate_token.py

import asyncio
import sys
from urllib.parse import urlparse, parse_qs
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from app.services.ebay.auth import EbayAuthManager

async def main():
    """
    Parses the full eBay redirect URL to extract the authorization code
    and exchanges it for a refresh token.
    """
    print("--- eBay Refresh Token Generator ---")
    
    # Get the full URL from the user
    full_url = input("✅ Please paste the FULL redirect URL from your browser and press Enter:\n> ")

    if not full_url.strip():
        print("❌ Error: URL cannot be empty.")
        return

    # --- NEW: Automatically extract the code from the URL ---
    try:
        parsed_url = urlparse(full_url)
        query_params = parse_qs(parsed_url.query)
        # parse_qs returns a list for each value, so we get the first one.
        # It also handles URL decoding automatically.
        auth_code = query_params.get('code', [None])[0]

        if not auth_code:
            raise ValueError("Could not find 'code' in the provided URL.")
            
        print("\n✅ Authorization code extracted successfully.")
    except Exception as e:
        print(f"❌ Error parsing URL: {e}")
        return
    # --- END NEW ---

    auth_manager = EbayAuthManager(sandbox=False)
    
    print("🔄 Exchanging code for a new refresh token...")
    try:
        # We pass the clean, decoded auth_code to the manager
        new_refresh_token = await auth_manager.generate_refresh_token(auth_code)
        
        if new_refresh_token:
            print("\n🎉 SUCCESS! 🎉")
            print("A new `ebay_tokens.json` file has been created with your tokens.")
        else:
            print("\n❌ FAILED: Could not generate a refresh token.")

    except Exception as e:
        print(f"\n❌ An error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(main())