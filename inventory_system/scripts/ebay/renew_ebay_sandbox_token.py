import asyncio
from app.services.ebay.auth import EbayAuthManager

async def main():
    auth_manager = EbayAuthManager(sandbox=True)
    
    # Step 1: Check current status
    print("=== Current Token Status ===")
    valid, days_left, access_valid, minutes_left = auth_manager.token_storage.get_token_expiry_info()
    print(f"Refresh token valid: {valid}, Days left: {days_left}")
    
    if not valid:
        # Step 2: Get authorization URL
        print("\n=== Get New Authorization ===")
        auth_url = auth_manager.get_authorization_url()
        print(f"Go to: {auth_url}")
        
        # Step 3: Get code from user
        auth_code = input("\nPaste authorization code here: ").strip()
        
        # Step 4: Generate refresh token
        print("\n=== Generating Refresh Token ===")
        try:
            refresh_token = await auth_manager.generate_refresh_token(auth_code)
            print(f"✅ Success! New refresh token: {refresh_token[:10]}...")
            
            # Step 5: Test access token
            access_token = await auth_manager.get_access_token()
            print(f"✅ Access token works: {access_token[:10]}...")
            
        except Exception as e:
            print(f"❌ Error: {str(e)}")
    else:
        print("✅ Refresh token is still valid!")

if __name__ == "__main__":
    asyncio.run(main())