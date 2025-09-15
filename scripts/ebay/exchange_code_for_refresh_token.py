import urllib.parse

from app.services.ebay.auth import EbayAuthManager

auth_manager = EbayAuthManager(sandbox=True)
token_storage = auth_manager.token_storage

# Use the authorization code you got from Step 3
encoded_auth_code = "v%5E1.1%23i%5E1%23r%5E1%23p%5E3%23I%5E3%23f%5E0%23t%5EUl41XzA6MEM0QUQ2Rjc2N0U3QjU2QTkxNkE3NERFNUZCMEVDMTdfMl8xI0VeMTI4NA%3D%3DD"
auth_code = urllib.parse.unquote(encoded_auth_code)
# Generate new refresh token
import asyncio
async def renew_token():
    try:
        refresh_token = await auth_manager.generate_refresh_token(auth_code)
        print(f"✅ New refresh token generated: {refresh_token[:10]}...")
        
        # Test getting access token
        access_token = await auth_manager.get_access_token()
        print(f"✅ Access token obtained: {access_token[:10]}...")
        
        return True
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

# Run it
success = asyncio.run(renew_token())
print(f"Token renewal {'successful' if success else 'failed'}")