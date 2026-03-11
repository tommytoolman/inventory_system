from app.services.ebay.auth import EbayAuthManager

# Check sandbox token status
auth_manager = EbayAuthManager(sandbox=False)
token_storage = auth_manager.token_storage

# Debug current status
token_storage.debug_token_storage()

# Check expiry info
valid, days_left, access_valid, minutes_left = token_storage.get_token_expiry_info()
print(f"Refresh token valid: {valid}, Days left: {days_left}")
print(f"Access token valid: {access_valid}, Minutes left: {minutes_left}")

# Generate the authorization URL
auth_url = auth_manager.get_authorization_url()
print(f"Go to this URL in your browser: {auth_url}")


"""
The Solution: A Fresh Authorization
Here is the full, step-by-step process to generate a new token with the correct permissions.

1. Confirm Code Change
- Ensure the self.scopes list in your app/services/ebay/auth.py file includes the sell.account scope, as we discussed.

2. Delete ALL Old Tokens (Crucial)
To prevent the old token from being used, you must remove it from everywhere:

Delete the token file: ebay_tokens.json.

Go into your .env file and delete or comment out the EBAY_REFRESH_TOKEN variable.

3. Run Your Initial Authorization Script
You need to run the script that generates the long eBay consent URL (the one that uses the get_authorization_url() method).

Run that script.

Copy the full URL it prints out.

4. Grant Consent in Your Browser

Paste the URL into your browser.

Log in to your eBay account.

You will see a new consent screen. This time, it will ask you to approve permissions for both "Inventory" and "Account Settings." This is how you know it's working.

Click "Agree and Continue."

5. Get the New Authorization Code

After you agree, eBay will redirect you to your RuName URL. The address bar will now contain a very long URL with a new authorization code.

It will look like this: https://your.redirect.url/path?code=v%5E1.1%...&expires_in=299

Copy the entire value after code= (it's very long and starts with v^1.1...).

6. Generate the New Refresh Token

Run the part of your script that uses the generate_refresh_token() method, pasting in the new authorization code you just copied.

This will create a brand new ebay_tokens.json file, and this time, the refresh token inside it will have the correct permissions.

7. Run the get_policies.py Script
Now, you can run the get_policies.py script. It will find the new token file, use it to get a valid access token with the correct scopes, and successfully fetch your policies.
"""

# v%5E1.1%23i%5E1%23f%5E0%23r%5E1%23p%5E3%23I%5E3%23t%5EUl41XzI6NkZBQTIwMDc5RDYzMDQ3RUYwRTc4QzRCMUY3NjJCQTVfMl8xI0VeMTI4NA%3D%3D