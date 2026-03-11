# scripts/ebay/list_business_policies.py
import asyncio
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

from app.services.ebay.trading import EbayTradingLegacyAPI

async def list_business_policies():
    """Fetch and display all business policies from eBay"""
    
    api = EbayTradingLegacyAPI(sandbox=False)
    
    # Get seller profiles (business policies)
    response = await api.execute_request('GetUserPreferences', {
        'ShowSellerProfilePreferences': 'true'
    })
    
    if response and 'SellerProfilePreferences' in response:
        profiles = response['SellerProfilePreferences']
        
        print("\n=== SHIPPING PROFILES ===")
        if 'SupportedSellerProfiles' in profiles:
            for profile in profiles['SupportedSellerProfiles']:
                if profile.get('CategoryGroup') == 'SHIPPING':
                    print(f"ID: {profile.get('ProfileID')}")
                    print(f"Name: {profile.get('ProfileName')}")
                    print(f"Type: {profile.get('ProfileType')}")
                    print("-" * 40)

if __name__ == "__main__":
    asyncio.run(list_business_policies())