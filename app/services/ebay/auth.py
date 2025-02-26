import os
import json
import base64
import logging
import httpx  # Using httpx instead of requests for async support

from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from fastapi import HTTPException

from app.core.config import get_settings
from app.core.exceptions import EbayAPIError

logger = logging.getLogger(__name__)


class TokenStorage:
    """Handles persistent storage of token information"""
    
    def __init__(self, storage_dir="tokens"):
        """
        Initialize the token storage
        
        Args:
            storage_dir: Directory to store token files
        """
        self.storage_dir = storage_dir
        self.token_file = os.path.join(storage_dir, "ebay_tokens.json")
        
        # Create directory if it doesn't exist
        os.makedirs(storage_dir, exist_ok=True)
        
        # Print debug info
        print(f"Token storage directory: {self.storage_dir}")
        print(f"Token file path: {self.token_file}")
    
    def save_token_info(self, token_data):
        """
        Save token information
        
        Args:
            token_data: Dictionary containing token data including expiration
        """
        try:
            # Calculate expiration dates if not already provided
            now = datetime.now()
            
            # If we have a new refresh token, calculate its expiration
            if 'refresh_token' in token_data and 'refresh_token_expires_in' in token_data:
                refresh_token_expires_at = now + timedelta(seconds=token_data["refresh_token_expires_in"])
                token_data['refresh_token_expires_at'] = refresh_token_expires_at.isoformat()
                token_data['refresh_token_created_at'] = now.isoformat()
                
                # Log when it will expire
                days_until_expiry = (refresh_token_expires_at - now).days
                logger.info(f"New refresh token will expire in {days_until_expiry} days")
            
            # If we have a new access token, calculate its expiration
            if 'access_token' in token_data and 'expires_in' in token_data:
                access_token_expires_at = now + timedelta(seconds=token_data["expires_in"])
                token_data['access_token_expires_at'] = access_token_expires_at.isoformat()
            
            # Load existing data to merge with new data
            existing_data = self.load_token_info()
            existing_data.update(token_data)
            
            # Write to file
            with open(self.token_file, 'w') as f:
                json.dump(existing_data, f, indent=2)
                
            logger.debug("Token information saved successfully")
                
        except Exception as e:
            logger.error(f"Error saving token information: {str(e)}")
    
    def load_token_info(self):
        """
        Load token information
        
        Returns:
            dict: Token information or empty dict if no file exists
        """
        try:
            if os.path.exists(self.token_file):
                with open(self.token_file, 'r') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            logger.error(f"Error loading token information: {str(e)}")
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


class EbayAuthManager:
    """
    Manages eBay API authentication tokens.
    
    Flow:
    1. Authorization Code (one-time, manual) -> Refresh Token (valid ~18 months)
    2. Refresh Token -> Access Token (valid 2 hours)
    
    This class manages storage, retrieval, and renewal of tokens as needed.
    """
    
    # Token storage path - consider moving this to a database or secure store in production
    TOKEN_FILE = "/Users/wommy/Documents/GitHub/PROJECTS/HANKS/inventory_system/app/services/ebay/tokens/ebay_tokens.json"
    
    def __init__(self):
        """Initialize the auth manager with settings"""
        self.settings = get_settings()
        self.client_id = self.settings.EBAY_CLIENT_ID
        self.client_secret = self.settings.EBAY_CLIENT_SECRET
        self.ru_name = self.settings.EBAY_RU_NAME
        
        # Get the absolute path to the tokens directory
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        tokens_dir = os.path.join(base_dir, "services", "ebay", "tokens")
        
        # Initialize token storage
        self.token_storage = TokenStorage(storage_dir="/Users/wommy/Documents/GitHub/PROJECTS/HANKS/inventory_system/app/services/ebay/tokens/")
        
        # Load refresh token from env or storage
        self.refresh_token = self.settings.EBAY_REFRESH_TOKEN or self.token_storage.load_token_info().get('refresh_token')
        
        # Check if refresh token is about to expire
        valid, days_left, _, _ = self.token_storage.get_token_expiry_info()
        if valid and days_left < 60:
            logger.warning(f"eBay refresh token will expire in {days_left} days. Consider generating a new one.")

        # Scopes required for your application
        self.scopes = [
            # "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
            "https://api.ebay.com/oauth/api_scope/sell.inventory",
            # "https://api.ebay.com/oauth/api_scope/sell.marketing",
            # "https://api.ebay.com/oauth/api_scope/sell.account",
            # "https://api.ebay.com/oauth/api_scope/commerce.catalog.readonly"
        ]
        
        print(self.scopes)
        
        # Load existing tokens if available
        self.tokens = self._load_tokens()
    
    def _load_tokens(self) -> Dict:
        """Load tokens, prioritizing environment variables for refresh token"""
        try:
            # Start with settings-based refresh token
            tokens = {
                "access_token": None,
                "refresh_token": self.settings.EBAY_REFRESH_TOKEN,
                "access_token_expires_at": None,
                "refresh_token_expires_at": None
            }
            
            # If token file exists, use it only for access token info
            if os.path.exists(self.TOKEN_FILE):
                with open(self.TOKEN_FILE, 'r') as f:
                    file_tokens = json.load(f)
                    # Only take access token details from file
                    tokens["access_token"] = file_tokens.get("access_token")
                    tokens["access_token_expires_at"] = file_tokens.get("access_token_expires_at")

            return tokens
        except Exception as e:
            logger.error(f"Error loading tokens: {str(e)}")
            return {
                "access_token": None,
                "refresh_token": self.settings.EBAY_REFRESH_TOKEN,
                "access_token_expires_at": None,
                "refresh_token_expires_at": None
            }

    def _save_tokens(self) -> None:
        """Save tokens to storage - only access token is saved to file"""
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(self.TOKEN_FILE), exist_ok=True)
            
            # Only save access token details to file
            with open(self.TOKEN_FILE, 'w') as f:
                token_data = {
                    "access_token": self.tokens["access_token"],
                    "access_token_expires_at": self.tokens["access_token_expires_at"]
                }
                json.dump(token_data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving tokens: {str(e)}")
    
    def get_authorization_url(self) -> str:
        """Generate the authorization URL for manual approval"""
        scopes = [
            "https://api.ebay.com/oauth/api_scope/sell.inventory",
            # "https://api.ebay.com/oauth/api_scope/sell.marketing",
            # "https://api.ebay.com/oauth/api_scope/sell.account",
            # "https://api.ebay.com/oauth/api_scope/sell.fulfillment"
        ]
        scopes_str = "%20".join(scopes)
        return (
            f"https://auth.ebay.com/oauth2/authorize"
            f"?client_id={self.client_id}"
            f"&redirect_uri={self.ru_name}"
            f"&response_type=code"
            f"&scope={scopes_str}"
        )
    
    async def generate_refresh_token(self, auth_code: str) -> str:
        """
        Exchange an authorization code for a refresh token.
        This should be used rarely - refresh tokens are valid for ~18 months.
        
        Args:
            auth_code: The authorization code from eBay
                
        Returns:
            str: The refresh token
                
        Raises:
            EbayAPIError: If the token exchange fails
        """
        token_url = "https://api.ebay.com/identity/v1/oauth2/token"
        
        # Prepare the authorization header
        auth_header = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {auth_header}"
        }
        
        data = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": self.ru_name
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(token_url, headers=headers, data=data)
                
                if response.status_code != 200:
                    logger.error(f"eBay token error: {response.text}")
                    raise EbayAPIError(f"Failed to get refresh token: {response.text}")
                
                token_data = response.json()
                
                # Save the token data using TokenStorage
                self.token_storage.save_token_info(token_data)
                
                # Log the refresh token expiration for monitoring
                days_until_expiry = int(token_data["refresh_token_expires_in"] / 86400)  # seconds to days
                logger.info(f"New refresh token generated. Valid for {days_until_expiry} days.")
                
                return token_data["refresh_token"]
                
        except httpx.RequestError as e:
            logger.error(f"Network error getting refresh token: {str(e)}")
            raise EbayAPIError(f"Network error getting refresh token: {str(e)}")
    
    async def get_access_token(self) -> str:
        """
        Get a valid access token, refreshing if necessary.
        
        Returns:
            str: The access token
            
        Raises:
            EbayAPIError: If getting the access token fails
        """
        # Check if we have a valid access token
        now = datetime.now()
        
        if (
            self.tokens["access_token"] 
            and self.tokens["access_token_expires_at"]
            and datetime.fromisoformat(self.tokens["access_token_expires_at"]) > now + timedelta(minutes=5)
        ):
            # Token is still valid (with 5-minute buffer)
            return self.tokens["access_token"]
        
        # Need to get a new access token using the refresh token
        if not self.tokens["refresh_token"]:
            raise EbayAPIError("No refresh token available. Please authorize the application.")
        
        # Check if refresh token is about to expire
        if (
            self.tokens["refresh_token_expires_at"]
            and datetime.fromisoformat(self.tokens["refresh_token_expires_at"]) < now + timedelta(days=60)
        ):
            # Refresh token expires within 60 days - log a warning
            days_left = (datetime.fromisoformat(self.tokens["refresh_token_expires_at"]) - now).days
            logger.warning(f"eBay refresh token expires in {days_left} days. Please generate a new one soon.")
        
        # Get a new access token
        token_url = "https://api.ebay.com/identity/v1/oauth2/token"
        
        # Prepare the authorization header
        auth_header = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {auth_header}"
        }
        
        # Prepare scopes
        scopes_str = " ".join(self.scopes)
        
        print(scopes_str)
        
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.tokens["refresh_token"],
            "scope": "https://api.ebay.com/oauth/api_scope/sell.inventory"
            # "scope": scopes_str
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(token_url, headers=headers, data=data)
                
                if response.status_code != 200:
                    logger.error(f"eBay token refresh error: {response.text}")
                    raise EbayAPIError(f"Failed to refresh access token: {response.text}")
                
                token_data = response.json()
                
                # Calculate expiration date
                access_token_expires_at = now + timedelta(seconds=token_data["expires_in"])
                
                # Update token storage
                self.tokens["access_token"] = token_data["access_token"]
                self.tokens["access_token_expires_at"] = access_token_expires_at.isoformat()
                
                self._save_tokens()
                
                return token_data["access_token"]
                
        except httpx.RequestError as e:
            logger.error(f"Network error refreshing access token: {str(e)}")
            raise EbayAPIError(f"Network error refreshing access token: {str(e)}")
    
    def check_refresh_token_expiry(self) -> Tuple[bool, Optional[int]]:
        """
        Check if the refresh token is about to expire.
        
        Returns:
            Tuple[bool, Optional[int]]: (is_expiring, days_left)
        """
        if not self.tokens["refresh_token_expires_at"]:
            # We don't know when it expires, assume it's fine
            return False, None
        
        now = datetime.now()
        expires_at = datetime.fromisoformat(self.tokens["refresh_token_expires_at"])
        days_left = (expires_at - now).days
        
        # Consider "about to expire" as less than 60 days
        return days_left < 60, days_left