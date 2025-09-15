# app/services/ebay/auth.py

import os
import json
import base64
import logging
import httpx  # Using httpx instead of requests for async support
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Tuple
# from fastapi import HTTPException # Note: HTTPException might not be appropriate for service layer, consider custom exceptions
from app.core.config import get_settings
from app.core.exceptions import EbayAPIError

logger = logging.getLogger(__name__)

class EbayAuthManager:
    """
    Manages eBay API authentication tokens.
    """  

    def __init__(self, sandbox=False):
        """Initialize the auth manager with settings"""
        print(f"DEBUG: EbayAuthManager.__init__ - Initializing. Sandbox: {sandbox}")
        self.settings = get_settings()
        self.sandbox = sandbox
        
        # Debug settings - these prints are good as they are.
        # print("DEBUG: EbayAuthManager.__init__ - Settings object type:", type(self.settings))
        
        if self.sandbox:
            sandbox_client_id = getattr(self.settings, 'EBAY_SANDBOX_CLIENT_ID', '')
            sandbox_client_secret = getattr(self.settings, 'EBAY_SANDBOX_CLIENT_SECRET', '')
            sandbox_ru_name = getattr(self.settings, 'EBAY_SANDBOX_RU_NAME', '')
            
            # print("DEBUG: EbayAuthManager.__init__ - Sandbox Settings:")
            # print(f"  EBAY_SANDBOX_CLIENT_ID: '{sandbox_client_id}'")
            # print(f"  EBAY_SANDBOX_CLIENT_SECRET (masked): '{'********' + sandbox_client_secret[-4:] if sandbox_client_secret and len(sandbox_client_secret) > 4 else 'Not set or too short'}'")
            # print(f"  EBAY_SANDBOX_RU_NAME: '{sandbox_ru_name}'")
            
            self.client_id = sandbox_client_id
            self.client_secret = sandbox_client_secret
            self.ru_name = sandbox_ru_name # Used for initial auth code generation
            self.token_file_name = "ebay_sandbox_tokens.json"
            self.auth_url = "https://auth.sandbox.ebay.com/oauth2/authorize" # For generating auth code
            self.token_refresh_url = "https://api.sandbox.ebay.com/identity/v1/oauth2/token" # For refreshing token
        else:
            prod_client_id = getattr(self.settings, 'EBAY_CLIENT_ID', '')
            prod_client_secret = getattr(self.settings, 'EBAY_CLIENT_SECRET', '')
            prod_ru_name = getattr(self.settings, 'EBAY_RU_NAME', '')

            # print("DEBUG: EbayAuthManager.__init__ - Production Settings:")
            # print(f"  EBAY_CLIENT_ID: '{prod_client_id}'")
            # print(f"  EBAY_CLIENT_SECRET (masked): '{'********' + prod_client_secret[-4:] if prod_client_secret and len(prod_client_secret) > 4 else 'Not set or too short'}'")
            # print(f"  EBAY_RU_NAME: '{prod_ru_name}'")

            self.client_id = prod_client_id
            self.client_secret = prod_client_secret
            self.ru_name = prod_ru_name
            self.token_file_name = "ebay_tokens.json"
            self.auth_url = "https://auth.ebay.com/oauth2/authorize"
            self.token_refresh_url = "https://api.ebay.com/identity/v1/oauth2/token"
        
        # print(f"DEBUG: EbayAuthManager.__init__ - Token refresh URL set to: {self.token_refresh_url}")

        # Get the absolute path to the tokens directory
        # This path construction for TOKEN_FILE was in your original code, so we keep it.
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        tokens_dir = os.path.join(base_dir, "services", "ebay", "tokens")
        self.TOKEN_FILE = os.path.join(tokens_dir, self.token_file_name)
        # print(f"DEBUG: EbayAuthManager.__init__ - self.TOKEN_FILE (for _load_tokens/_save_tokens logic) set to: {self.TOKEN_FILE}")
        
        # Initialize token storage with the correct tokens_dir for TokenStorage class instance
        self.token_storage = TokenStorage(
            storage_dir=tokens_dir, 
            token_file_name=self.token_file_name
        )
        # print(f"DEBUG: EbayAuthManager.__init__ - TokenStorage instance created for file: {self.token_storage.token_file}")
        
        # Load refresh token from env or storage
        # Your original logic for self.refresh_token
        if self.sandbox:
            sandbox_refresh_token_env = getattr(self.settings, 'EBAY_SANDBOX_REFRESH_TOKEN', '')
            # print(f"DEBUG: EbayAuthManager.__init__ - Sandbox refresh token from .env: {'********' + sandbox_refresh_token_env[-5:] if sandbox_refresh_token_env and len(sandbox_refresh_token_env) > 5 else 'Not set or too short'}")
            loaded_info_for_refresh_init = self.token_storage.load_token_info() # This will print
            refresh_from_file_init = loaded_info_for_refresh_init.get('refresh_token', '')
            # print(f"DEBUG: EbayAuthManager.__init__ - Sandbox refresh token from file store: {'********' + refresh_from_file_init[-5:] if refresh_from_file_init and len(refresh_from_file_init) > 5 else 'Not set or too short'}")
            self.refresh_token = sandbox_refresh_token_env or refresh_from_file_init
        else:
            prod_refresh_token_env = getattr(self.settings, 'EBAY_REFRESH_TOKEN', '')
            # print(f"DEBUG: EbayAuthManager.__init__ - Production refresh token from .env: {'********' + prod_refresh_token_env[-5:] if prod_refresh_token_env and len(prod_refresh_token_env) > 5 else 'Not set or too short'}")
            loaded_info_for_refresh_init_prod = self.token_storage.load_token_info() # This will print
            refresh_from_file_init_prod = loaded_info_for_refresh_init_prod.get('refresh_token', '')
            # print(f"DEBUG: EbayAuthManager.__init__ - Production refresh token from file store: {'********' + refresh_from_file_init_prod[-5:] if refresh_from_file_init_prod and len(refresh_from_file_init_prod) > 5 else 'Not set or too short'}")
            self.refresh_token = prod_refresh_token_env or refresh_from_file_init_prod
        
        # print(f"DEBUG: EbayAuthManager.__init__ - Final self.refresh_token (masked): {'********' + self.refresh_token[-5:] if self.refresh_token and len(self.refresh_token) > 5 else 'Not set or too short'}")

        # Scopes required for your application
        self.scopes = [
            "https://api.ebay.com/oauth/api_scope/sell.inventory",
            # "https://api.ebay.com/oauth/api_scope/sell.account" # <-- The new scope for policiess
            # Add any other scopes you use, like sell.fulfillment, here
        ]
        self.scope_string = " ".join(self.scopes) # <-- Add this line
        print(f"DEBUG: EbayAuthManager.__init__ - Scopes set to: {self.scopes}")
        
        # Load existing tokens if available
        self.tokens = self._load_tokens() # This uses your original _load_tokens logic
        print(f"DEBUG: EbayAuthManager.__init__ - Initial self.tokens after _load_tokens(): Keys={list(self.tokens.keys()) if isinstance(self.tokens, dict) else 'Not a dict'}, AccessToken={self.tokens.get('access_token', 'None')[:10] if self.tokens.get('access_token') else 'None'}..., ExpiresAt={self.tokens.get('access_token_expires_at')}")
    
    def _load_tokens(self) -> Dict:
        """Load tokens, prioritizing environment variables for refresh token"""
        # print(f"DEBUG: EbayAuthManager._load_tokens - Entered. self.refresh_token already set in __init__ (masked): {'********' + self.refresh_token[-5:] if self.refresh_token and len(self.refresh_token) > 5 else 'Not set or too short'}")
        try:
            tokens = {
                "access_token": None,
                "refresh_token": self.refresh_token, # This was set in __init__
                "access_token_expires_at": None,
                "refresh_token_expires_at": None # Your original didn't set this here, TokenStorage might
            }
            
            if os.path.exists(self.TOKEN_FILE): # Using self.TOKEN_FILE from __init__
                # print(f"DEBUG: EbayAuthManager._load_tokens - Token file {self.TOKEN_FILE} exists. Loading access token details.")
                with open(self.TOKEN_FILE, 'r') as f:
                    file_tokens = json.load(f)
                    # print(f"DEBUG: EbayAuthManager._load_tokens - Data from file {self.TOKEN_FILE}: Keys={list(file_tokens.keys())}")
                    tokens["access_token"] = file_tokens.get("access_token")
                    tokens["access_token_expires_at"] = file_tokens.get("access_token_expires_at")
                    # If the main refresh token is also in the file and you want to prioritize file over .env for some reason:
                    # if 'refresh_token' in file_tokens and not self.refresh_token: # Example: only if .env was empty
                    #    tokens['refresh_token'] = file_tokens.get('refresh_token')
                    #    self.refresh_token = tokens['refresh_token'] # Update instance attribute if loaded from file
                    #    print(f"DEBUG: EbayAuthManager._load_tokens - Updated self.refresh_token from file.")
            else:
                print(f"DEBUG: EbayAuthManager._load_tokens - Token file {self.TOKEN_FILE} does not exist.")

            # print(f"DEBUG: EbayAuthManager._load_tokens - Returning tokens. AccessToken (masked): {'********' + tokens.get('access_token', '')[-5:] if tokens.get('access_token') and len(tokens.get('access_token', '')) > 5 else 'None/Too short'}, ExpiresAt: {tokens.get('access_token_expires_at')}")
            return tokens
        except Exception as e:
            # print(f"DEBUG: EbayAuthManager._load_tokens - EXCEPTION: {e}")
            logger.error(f"Error loading tokens: {str(e)}")
            # Fallback, ensuring self.refresh_token (from init) is preserved
            return {
                "access_token": None,
                "refresh_token": self.refresh_token,
                "access_token_expires_at": None,
                "refresh_token_expires_at": None
            }

    def _save_tokens(self) -> None:
        """Save tokens to storage - only access token details are saved to file by this method"""
        # print(f"DEBUG: EbayAuthManager._save_tokens - Entered. Attempting to save access token details to {self.TOKEN_FILE}")
        # print(f"DEBUG: EbayAuthManager._save_tokens - Current self.tokens['access_token'] (masked): {'********' + self.tokens.get('access_token', '')[-5:] if self.tokens.get('access_token') and len(self.tokens.get('access_token', '')) > 5 else 'None/Too short'}")
        # print(f"DEBUG: EbayAuthManager._save_tokens - Current self.tokens['access_token_expires_at']: {self.tokens.get('access_token_expires_at')}")

        try:
            os.makedirs(os.path.dirname(self.TOKEN_FILE), exist_ok=True)
            # print(f"DEBUG: EbayAuthManager._save_tokens - Ensured directory exists for {self.TOKEN_FILE}")
            
            # Only save access token details as per your original method's intent
            token_data_to_save = {
                "access_token": self.tokens.get("access_token"),
                "access_token_expires_at": self.tokens.get("access_token_expires_at")
                # NOTE: Your original `TokenStorage.save_token_info` might save more if `token_data` has more.
                # This method `_save_tokens` in `EbayAuthManager` specifically prepares a dict with just these two.
                # If `TokenStorage.save_token_info` *merges*, ensure this is the desired behavior.
                # Based on `TokenStorage.save_token_info`'s `existing_data.update(token_data)`, it will merge this minimal dict.
            }
            
            # print(f"DEBUG: EbayAuthManager._save_tokens - Data being passed to TokenStorage.save_token_info: {token_data_to_save}")
            # Calling TokenStorage to handle the actual file write
            self.token_storage.save_token_info(token_data_to_save) # This will have its own debug prints
            # No need to log "Tokens saved to..." here as TokenStorage does it.
            logger.info(f"Access token details potentially updated in {self.TOKEN_FILE} via TokenStorage.")
        except Exception as e:
            # print(f"DEBUG: EbayAuthManager._save_tokens - EXCEPTION: {e}")
            logger.error(f"Error saving tokens: {str(e)}")
    
    def get_authorization_url(self) -> str:
        """Generate the authorization URL for manual approval"""
        # This method seems fine as is, just adding entry/exit prints.
        # print(f"DEBUG: EbayAuthManager.get_authorization_url - Entered. Auth URL: {self.auth_url}, Client ID: {self.client_id}, RuName: {self.ru_name}")
        scopes_str = "%20".join(self.scopes)
        auth_url_generated = (
            f"{self.auth_url}"
            f"?client_id={self.client_id}"
            f"&redirect_uri={self.ru_name}"
            f"&response_type=code"
            f"&scope={scopes_str}"
        )
        # print(f"DEBUG: EbayAuthManager.get_authorization_url - Generated URL: {auth_url_generated}")
        return auth_url_generated
    
    async def generate_refresh_token(self, auth_code: str) -> str:
        """
        Exchange an authorization code for a refresh token.
        """
        # print(f"DEBUG: EbayAuthManager.generate_refresh_token - Entered. Auth code (masked): {'********' + auth_code[-5:] if auth_code and len(auth_code) > 5 else 'Not available or too short'}")
        # Original code had: token_url = "https://api.ebay.com/identity/v1/oauth2/token"
        # This should use self.token_refresh_url set in __init__ for consistency with sandbox/prod
        current_token_refresh_url = self.token_refresh_url 
        # print(f"DEBUG: EbayAuthManager.generate_refresh_token - Using token refresh URL: {current_token_refresh_url}")
        
        auth_header = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        # print(f"DEBUG: EbayAuthManager.generate_refresh_token - Client ID for basic auth (masked): {self.client_id[:5]}...")
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {auth_header}"
        }
        masked_headers = {k: ('Basic ********' if k == 'Authorization' else v) for k,v in headers.items()}
        # print(f"DEBUG: EbayAuthManager.generate_refresh_token - Request Headers (auth masked): {masked_headers}")
        
        data = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": self.ru_name # RuName from init
        }
        # print(f"DEBUG: EbayAuthManager.generate_refresh_token - Request Data: {data}")
        
        try:
            async with httpx.AsyncClient() as client:
                # print(f"DEBUG: EbayAuthManager.generate_refresh_token - Posting to {current_token_refresh_url}")
                response = await client.post(current_token_refresh_url, headers=headers, data=data)
                # print(f"DEBUG: EbayAuthManager.generate_refresh_token - Response status: {response.status_code}")
                # print(f"DEBUG: EbayAuthManager.generate_refresh_token - Response content: {response.text[:500]}") # Careful logging full response

                if response.status_code != 200:
                    error_text = response.text
                    # print(f"DEBUG: EbayAuthManager.generate_refresh_token - ERROR - Status {response.status_code}, Body: {error_text[:500]}")
                    logger.error(f"eBay token error (generate_refresh_token): {error_text}")
                    raise EbayAPIError(f"Failed to get refresh token: {error_text}")
                
                token_data_from_response = response.json()
                # print(f"DEBUG: EbayAuthManager.generate_refresh_token - Success. Response keys: {list(token_data_from_response.keys())}")
                
                # Save the token data using TokenStorage - your original code calls self.token_storage.save_token_info
                # This will save access_token, refresh_token, and calculate expiries if 'expires_in' fields are present.
                # print(f"DEBUG: EbayAuthManager.generate_refresh_token - Calling token_storage.save_token_info with received token_data.")
                self.token_storage.save_token_info(token_data_from_response) # This will have its own prints
                
                # Update the instance's self.refresh_token and self.tokens if needed
                if "refresh_token" in token_data_from_response:
                    self.refresh_token = token_data_from_response["refresh_token"]
                    # print(f"DEBUG: EbayAuthManager.generate_refresh_token - Updated self.refresh_token (masked): {'********' + self.refresh_token[-5:] if self.refresh_token and len(self.refresh_token)>5 else 'Not set'}")
                if "access_token" in token_data_from_response: # Also update current access token
                    self.tokens = self._load_tokens() # Reload to get the newly saved access token details
                    # print(f"DEBUG: EbayAuthManager.generate_refresh_token - Reloaded self.tokens after saving new refresh grant.")

                days_until_expiry = int(token_data_from_response.get("refresh_token_expires_in", 0) / 86400)
                # print(f"DEBUG: EbayAuthManager.generate_refresh_token - New refresh token obtained. Expected to be valid for ~{days_until_expiry} days (based on refresh_token_expires_in if present).")
                logger.info(f"New refresh token generated. Valid for {days_until_expiry} days.")
                
                return token_data_from_response["refresh_token"]
                
        except httpx.RequestError as e:
            # print(f"DEBUG: EbayAuthManager.generate_refresh_token - httpx.RequestError: {e}")
            logger.error(f"Network error getting refresh token: {str(e)}")
            raise EbayAPIError(f"Network error getting refresh token: {str(e)}")
        except Exception as e_gen:
            # print(f"DEBUG: EbayAuthManager.generate_refresh_token - Generic EXCEPTION: {e_gen}")
            logger.error(f"Generic error in generate_refresh_token: {str(e_gen)}", exc_info=True)
            raise EbayAPIError(f"Unexpected error generating refresh token: {str(e_gen)}")

    
    async def get_access_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""
        
        # print(f"DEBUG: EbayAuthManager.get_access_token - Entered method.") # Your existing print "*** ENTERED get_access_token() METHOD ***" is also fine
        
        now = datetime.now() # Naive datetime
        # print(f"DEBUG: EbayAuthManager.get_access_token - Current time (naive for comparison): {now.isoformat()}")
        
        # Load token info directly from storage to ensure we have the latest
        # Your original code uses self.token_storage.load_token_info()
        # My previous advice used self.tokens which is loaded in __init__ and after refresh.
        # Let's stick to your direct load for checking:
        current_token_info_from_storage = self.token_storage.load_token_info() # This will have its own prints
        # print(f"DEBUG: EbayAuthManager.get_access_token - Loaded current_token_info_from_storage. Keys: {list(current_token_info_from_storage.keys()) if isinstance(current_token_info_from_storage, dict) else 'Not a dict'}")

        # Use self.refresh_token which was initialized from .env or file in __init__
        # This 'refresh_token' variable in your original was shadowed by the one from load_token_info
        # Let's use the instance's self.refresh_token for consistency
        current_refresh_token_instance = self.refresh_token 
        # print(f"DEBUG: EbayAuthManager.get_access_token - Using self.refresh_token (masked from __init__): {'********' + current_refresh_token_instance[-5:] if current_refresh_token_instance and len(current_refresh_token_instance) > 5 else 'None or too short'}")
        
        access_token = current_token_info_from_storage.get('access_token')
        access_token_expires_at_str = current_token_info_from_storage.get('access_token_expires_at')
        
        # print(f"DEBUG: EbayAuthManager.get_access_token - Access token from storage (masked): {'********' + access_token[-5:] if access_token and len(access_token) > 5 else 'None or too short'}")
        # print(f"DEBUG: EbayAuthManager.get_access_token - Access token expires_at string from storage: {access_token_expires_at_str}")
        
        if access_token and access_token_expires_at_str:
            try:
                expires_at_dt = datetime.fromisoformat(access_token_expires_at_str)
                # If expires_at_dt is timezone-aware, make 'now' aware too for direct comparison.
                # Assuming expires_at_dt might be naive as per TokenStorage saving logic.
                # If expires_at_dt is UTC, now should be datetime.now(timezone.utc)
                # For now, continuing with naive comparison as per original structure.
                # print(f"DEBUG: EbayAuthManager.get_access_token - Parsed expires_at_dt: {expires_at_dt.isoformat()}")
                if expires_at_dt > now + timedelta(minutes=5):
                    # print(f"DEBUG: EbayAuthManager.get_access_token - Token is valid and not expiring soon. Returning existing token.")
                    # print(f"DEBUG: EbayAuthManager.get_access_token - Token value (masked): {'********' + access_token[-5:] if access_token and len(access_token) > 5 else 'None'}")
                    return access_token
                else:
                    print(f"DEBUG: EbayAuthManager.get_access_token - Token expired or expiring soon. Expires: {expires_at_dt.isoformat()}, Now: {now.isoformat()}")
            except ValueError as e_parse:
                print(f"DEBUG: EbayAuthManager.get_access_token - ValueError parsing access_token_expires_at '{access_token_expires_at_str}': {e_parse}. Proceeding to refresh.")
        else:
            print(f"DEBUG: EbayAuthManager.get_access_token - No valid access token or expiry in storage. Proceeding to refresh.")
        
        # print(f"DEBUG: EbayAuthManager.get_access_token - *** NEED TO REFRESH ACCESS TOKEN ***")
        
        if not current_refresh_token_instance: # Check the instance's refresh token
            # print("DEBUG: EbayAuthManager.get_access_token - ERROR: No self.refresh_token available. Please authorize the application.")
            logger.error("No self.refresh_token available. Please authorize the application.")
            raise EbayAPIError("No refresh token available. Please authorize the application.")
        
        # Use self.token_refresh_url set in __init__
        active_token_refresh_url = self.token_refresh_url 
        # print(f"DEBUG: EbayAuthManager.get_access_token - Using token refresh URL: {active_token_refresh_url}")
        
        auth_header = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {auth_header}"
        }
        masked_headers_refresh = {k: ('Basic ********' if k == 'Authorization' else v) for k,v in headers.items()}
        # print(f"DEBUG: EbayAuthManager.get_access_token - Refresh Request Headers (auth masked): {masked_headers_refresh}")
        
        data = {
            "grant_type": "refresh_token",
            "refresh_token": current_refresh_token_instance, # Use instance's refresh token
            "scope": " ".join(self.scopes) # Scopes from instance
        }
        # print(f"DEBUG: EbayAuthManager.get_access_token - Refresh Request Data (refresh_token masked): {{'grant_type': '{data['grant_type']}', 'refresh_token': '********{data['refresh_token'][-5:] if data['refresh_token'] and len(data['refresh_token']) > 5 else 'Not set'}', 'scope': '{data['scope']}'}}")
        
        try:
            async with httpx.AsyncClient() as client:
                # print(f"DEBUG: EbayAuthManager.get_access_token - Posting to refresh token URL: {active_token_refresh_url}")
                response = await client.post(active_token_refresh_url, headers=headers, data=data)
                # print(f"DEBUG: EbayAuthManager.get_access_token - Refresh response status: {response.status_code}")
                # print(f"DEBUG: EbayAuthManager.get_access_token - Refresh response content: {response.text[:500]}") # Careful with full response

                if response.status_code != 200:
                    error_text_refresh = response.text
                    # print(f"DEBUG: EbayAuthManager.get_access_token - ERROR refreshing token. Status {response.status_code}, Body: {error_text_refresh[:500]}")
                    logger.error(f"eBay token refresh error: {error_text_refresh}")
                    # If refresh token is invalid (e.g. "invalid_grant"), it should be handled.
                    # Perhaps clear it from .env and file? For now, just raising.
                    if "invalid_grant" in error_text_refresh.lower():
                         print(f"DEBUG: EbayAuthManager.get_access_token - 'invalid_grant' detected for refresh_token. The refresh token itself might be bad or revoked.")
                    raise EbayAPIError(f"Failed to refresh access token: {error_text_refresh}")
                
                token_data_from_refresh_response = response.json()
                print(f"DEBUG: EbayAuthManager.get_access_token - Refresh successful. Response keys: {list(token_data_from_refresh_response.keys())}")
                
                # Calculate new expiration for the access token
                # Your original TokenStorage.save_token_info calculates 'access_token_expires_at' if 'expires_in' is present
                # Let's ensure the data passed to save_token_info includes 'expires_in'
                # The token_data_from_refresh_response *should* contain 'access_token' and 'expires_in'.
                # It *might* contain a new 'refresh_token' and 'refresh_token_expires_in'.
                
                # Update self.tokens in memory (important for subsequent calls in same session if any)
                self.tokens["access_token"] = token_data_from_refresh_response["access_token"]
                if "expires_in" in token_data_from_refresh_response:
                    new_expires_at = datetime.now() + timedelta(seconds=token_data_from_refresh_response["expires_in"])
                    self.tokens["access_token_expires_at"] = new_expires_at.isoformat()
                else: # Should not happen with a valid eBay response
                    self.tokens["access_token_expires_at"] = (datetime.now() + timedelta(hours=2)).isoformat() # Fallback
                    print(f"DEBUG: EbayAuthManager.get_access_token - WARNING: 'expires_in' not in refresh response. Using default 2hr expiry.")

                # If eBay returns a new refresh token, update it in memory and for saving
                if "refresh_token" in token_data_from_refresh_response:
                    self.tokens["refresh_token"] = token_data_from_refresh_response["refresh_token"]
                    self.refresh_token = self.tokens["refresh_token"] # Update instance variable
                    print(f"DEBUG: EbayAuthManager.get_access_token - New refresh token received and updated in memory (masked): {'********' + self.refresh_token[-5:] if self.refresh_token and len(self.refresh_token) > 5 else 'Not set'}")
                if "refresh_token_expires_in" in token_data_from_refresh_response: # Also update its expiry
                    new_refresh_expires_at = datetime.now() + timedelta(seconds=token_data_from_refresh_response["refresh_token_expires_in"])
                    self.tokens["refresh_token_expires_at"] = new_refresh_expires_at.isoformat()

                # Prepare data for TokenStorage.save_token_info.
                # It needs the new access_token, its calculated expires_at,
                # and potentially the new refresh_token and its calculated expires_at.
                # TokenStorage.save_token_info merges this with existing data.
                # The keys used in save_token_info are 'access_token', 'refresh_token',
                # and it calculates 'access_token_expires_at' and 'refresh_token_expires_at' IF
                # 'expires_in' and 'refresh_token_expires_in' are present in the dict passed to it.
                data_to_store = {
                    "access_token": self.tokens["access_token"],
                    "expires_in": token_data_from_refresh_response.get("expires_in") # For TokenStorage to calc expiry
                }
                if "refresh_token" in token_data_from_refresh_response: # If eBay sent a new one
                    data_to_store["refresh_token"] = self.tokens["refresh_token"]
                if "refresh_token_expires_in" in token_data_from_refresh_response:
                    data_to_store["refresh_token_expires_in"] = token_data_from_refresh_response.get("refresh_token_expires_in")

                print(f"DEBUG: EbayAuthManager.get_access_token - Calling token_storage.save_token_info with data containing new access token details (and potentially refresh token details).")
                self.token_storage.save_token_info(data_to_store) # This has its own prints
                
                newly_refreshed_access_token = self.tokens["access_token"]
                print(f"DEBUG: EbayAuthManager.get_access_token - Returning newly refreshed access token (masked): {'********' + newly_refreshed_access_token[-5:] if newly_refreshed_access_token and len(newly_refreshed_access_token)>5 else 'None'}")
                return newly_refreshed_access_token
        except httpx.RequestError as e_http:
            print(f"DEBUG: EbayAuthManager.get_access_token - httpx.RequestError during refresh: {e_http}")
            logger.error(f"Network error refreshing access token: {str(e_http)}")
            raise EbayAPIError(f"Network error refreshing access token: {str(e_http)}")
        except Exception as e_gen_refresh: # Catch any other errors during the refresh process
            print(f"DEBUG: EbayAuthManager.get_access_token - Generic EXCEPTION during refresh logic: {e_gen_refresh}")
            logger.error(f"Generic error during access token refresh: {str(e_gen_refresh)}", exc_info=True)
            raise EbayAPIError(f"Unexpected error refreshing access token: {str(e_gen_refresh)}")

    
    def check_refresh_token_expiry(self) -> Tuple[bool, Optional[int]]:
        """
        Check if the refresh token is about to expire.
        """
        print(f"DEBUG: EbayAuthManager.check_refresh_token_expiry - Entered.")
        # self.tokens["refresh_token_expires_at"] might not be set if only .env refresh token is used
        # and file was never saved with refresh_token_expires_in from an auth code grant.
        # TokenStorage.get_token_expiry_info loads directly from file.
        
        # Use TokenStorage to get consistent expiry info from the file
        refresh_is_valid_from_storage, days_left_from_storage, _, _ = self.token_storage.get_token_expiry_info()
        print(f"DEBUG: EbayAuthManager.check_refresh_token_expiry - Info from TokenStorage: refresh_valid={refresh_is_valid_from_storage}, days_left={days_left_from_storage}")

        # If your .env has EBAY_REFRESH_TOKEN_EXPIRY, you might want to parse and check that too,
        # or ensure TokenStorage is the single source of truth for expiry IF a refresh token grant
        # (generate_refresh_token) has been performed and saved its `refresh_token_expires_in`.
        # The current logic in __init__ doesn't use EBAY_REFRESH_TOKEN_EXPIRY from .env to populate self.tokens.
        
        # For now, relying on what TokenStorage provides as it reads the file where expiries should be stored.
        if not refresh_is_valid_from_storage: # If file says invalid or no expiry info
            # If refresh_token_expires_at is not in the file, days_left_from_storage would be 0, valid would be False.
            # We might not know when it expires, assume it's okay unless explicitly told it's bad.
            # Or, if it's missing, it implies we never got an expiry for it.
            # If self.refresh_token exists (from .env or file), we can't be sure of its expiry without more info.
            print(f"DEBUG: EbayAuthManager.check_refresh_token_expiry - TokenStorage indicates refresh token expiry info not sufficient or token invalid. Days left from storage: {days_left_from_storage}.")
            # If there's a refresh token from .env but no expiry in file, can't determine.
            # This method's original logic relied on self.tokens["refresh_token_expires_at"]
            # which might not be populated if only .env refresh token is used.
            # Let's try to use the .env expiry if available as a fallback.
            env_refresh_expiry_str = None
            if self.sandbox:
                env_refresh_expiry_str = getattr(self.settings, 'EBAY_SANDBOX_REFRESH_TOKEN_EXPIRY', None)
            else:
                env_refresh_expiry_str = getattr(self.settings, 'EBAY_REFRESH_TOKEN_EXPIRY', None)

            if env_refresh_expiry_str:
                print(f"DEBUG: EbayAuthManager.check_refresh_token_expiry - Found refresh token expiry in .env: {env_refresh_expiry_str}")
                try:
                    expires_at_env = datetime.fromisoformat(env_refresh_expiry_str.replace('Z', '+00:00')) # Handle Z for UTC
                    now_utc_check = datetime.now(timezone.utc)
                    days_left_env = (expires_at_env - now_utc_check).days
                    is_expiring_env = days_left_env < 60
                    print(f"DEBUG: EbayAuthManager.check_refresh_token_expiry - From .env: Expires_at={expires_at_env}, Days_left={days_left_env}, Is_expiring={is_expiring_env}")
                    return is_expiring_env, days_left_env
                except ValueError as e_parse_env:
                    print(f"DEBUG: EbayAuthManager.check_refresh_token_expiry - Error parsing .env refresh token expiry '{env_refresh_expiry_str}': {e_parse_env}")
                    # Fallback to what storage said, or assume not expiring if storage had no info
                    return False, None # Or days_left_from_storage if that was somewhat valid (e.g. 0 means unknown)
            else: # No expiry in .env either
                print("DEBUG: EbayAuthManager.check_refresh_token_expiry - No refresh token expiry found in .env settings either.")
                return False, None # Cannot determine, assume not expiring for now.
        
        # Using days_left from TokenStorage if it was valid
        is_expiring_storage = days_left_from_storage < 60
        print(f"DEBUG: EbayAuthManager.check_refresh_token_expiry - Using TokenStorage result: Is_expiring={is_expiring_storage}, Days_left={days_left_from_storage}")
        return is_expiring_storage, days_left_from_storage


class TokenStorage:
    """Handles persistent storage of token information"""
    
    def __init__(self, storage_dir=None, token_file_name="ebay_tokens.json"):
        """
        Initialize the token storage
        
        Args:
            storage_dir: Directory to store token files
        """
        self.storage_dir = storage_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "tokens")
        os.makedirs(self.storage_dir, exist_ok=True)
        self.token_file_name = token_file_name
        self.token_file = os.path.join(self.storage_dir, self.token_file_name)
        # print(f"DEBUG: TokenStorage.__init__ - Token storage directory: {self.storage_dir}")
        # print(f"DEBUG: TokenStorage.__init__ - Token file path: {self.token_file}")

    
    def save_token_info(self, token_data):
        """
        Save token information
        
        Args:
            token_data: Dictionary containing token data including expiration
        """
        # print(f"DEBUG: TokenStorage.save_token_info - Attempting to save tokens to {self.token_file}")
        
        try:
            # Create directory if it doesn't exist
            os.makedirs(self.storage_dir, exist_ok=True)
            
            # Load existing token data if it exists
            existing_data = self.load_token_info()
            
            # Update with new token data
            existing_data.update(token_data)
            
            # Add formatted expiration dates
            if "expires_in" in token_data:
                expires_at = datetime.now() + timedelta(seconds=token_data["expires_in"])
                existing_data["access_token_expires_at"] = expires_at.isoformat()
                
            if "refresh_token_expires_in" in token_data:
                refresh_expires_at = datetime.now() + timedelta(seconds=token_data["refresh_token_expires_in"])
                existing_data["refresh_token_expires_at"] = refresh_expires_at.isoformat()
            
            # Write to file
            with open(self.token_file, 'w') as f:
                json.dump(existing_data, f, indent=2)
                
            return True
        except Exception as e:
            logger.error(f"Error saving token info: {str(e)}")
            return False


    def load_token_info(self):
        """Load token information from storage"""
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading token info: {str(e)}")
                return {}
        else:
            # Return empty dict if file doesn't exist yet
            return {}       


    def get_token_expiry_info(self):
        """
        Get information about token expiration
        
        Returns:
            tuple: (refresh_token_valid, days_left, access_token_valid, minutes_left)
        """
        token_info = self.load_token_info()
        now = datetime.now()
        
        # Check refresh token
        refresh_token_valid = False
        days_left = 0
        
        if 'refresh_token_expires_at' in token_info:
            expires_at = datetime.fromisoformat(token_info['refresh_token_expires_at'])
            days_left = (expires_at - now).days
            refresh_token_valid = days_left > 0
        
        # Check access token
        access_token_valid = False
        minutes_left = 0
        
        if 'access_token_expires_at' in token_info:
            expires_at = datetime.fromisoformat(token_info['access_token_expires_at'])
            minutes_left = int((expires_at - now).total_seconds() / 60)
            access_token_valid = minutes_left > 0
        
        return (refresh_token_valid, days_left, access_token_valid, minutes_left)

    
    def is_refresh_token_valid(self, min_days=60):
        """
        Check if refresh token is valid and not expiring soon
        
        Args:
            min_days: Minimum days required for validity
            
        Returns:
            bool: True if token is valid and not expiring soon
        """
        valid, days_left, _, _ = self.get_token_expiry_info()
        return valid and days_left > min_days

    
    def debug_token_storage(self):
        """Print debug information for token storage"""
        print("\n===== TOKEN STORAGE DEBUG =====")
        print(f"Storage directory: {os.path.abspath(self.storage_dir)}")
        print(f"Token file path: {os.path.abspath(self.token_file)}")
        print(f"Token file exists: {os.path.exists(self.token_file)}")
        
        # Try to list files in the directory
        if os.path.exists(self.storage_dir):
            print(f"Files in directory: {os.listdir(self.storage_dir)}")
        else:
            print("Storage directory does not exist")
        
        # Check token info
        token_info = self.load_token_info()
        if token_info:
            print("Token info keys:", list(token_info.keys()))
            if 'refresh_token' in token_info:
                rt = token_info['refresh_token']
                print(f"Refresh token: {'*'*10}{rt[-5:]}")
            if 'refresh_token_expires_at' in token_info:
                exp = datetime.fromisoformat(token_info['refresh_token_expires_at'])
                print(f"Refresh token expires: {exp.strftime('%Y-%m-%d')}")
        else:
            print("No token info found")