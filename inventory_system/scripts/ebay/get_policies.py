import asyncio
import json
from app.services.ebay.trading import EbayAccountAPI # Assuming you added the class there

async def main():
    print("Fetching eBay Business Policies...")
    # Set sandbox=True if you need to check the sandbox environment
    account_api = EbayAccountAPI(sandbox=False) 
    
    try:
        policies = await account_api.get_business_policies()
        
        print("\n--- Found Policies ---")
        for policy in policies.get("policyProfiles", []):
            print(
                f"Name: {policy.get('name')}\n"
                f"  Type: {policy.get('policyType')}\n"
                f"  ID:   {policy.get('profileId')}\n" 
            )
        
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(main())
    
""" 
You have done everything perfectly on your end. The code is correct, the token is valid, and the scopes are right. I understand your frustration completely, but this final, confusing error points to the solution.

The problem is not in your code; it's a setting on the eBay seller account itself.

The Root Cause: An eBay Account Setting
Many eBay accounts, especially ones that have been active for a while, need to be manually opted-in to the Business Policies feature before the corresponding API endpoints become active.

Think of it as a feature that is "installed" on eBay's side but is "turned off" by default for your account. Until you go to your account settings and flip the switch on, the API literally cannot find the resource for your account, which is why it returns the 404 Not Found error.

The Solution: How to Opt-In to Business Policies ✅
Your colleague will need to log in to the eBay seller account (the one you've been using for the consent screen) and enable this feature.

Here are the steps:

Log in to your client's eBay seller account on the eBay UK website.

Once logged in, visit this specific opt-in URL:
https://www.bizpolicy.ebay.co.uk/businesspolicy/policyoptin

You should see a page explaining Business Policies. Click the "Get Started" or "Opt In" button.

Follow the prompts. This will migrate the account to the Business Policies model.

What Happens Next
After you've opted in, wait about 5-10 minutes for the change to take effect across eBay's systems.

Then, run the get_policies.py script one more time.

This is a frustrating and poorly documented step in the eBay integration process, but it is almost certainly the final hurdle. Once the account is opted-in, the API call will work.
"""