"""
eBay Authentication Manager using secure in-memory token storage
No tokens are ever saved to files - only stored in memory
"""

import os
import json
import base64
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict

import httpx

from app.core.config import get_settings
from app.core.exceptions import EbayAPIError
from .token_manager import SecureTokenManager

logger = logging.getLogger(__name__)


class EbayAuthManager:
    """
    Manages eBay OAuth authentication using secure in-memory storage
    """

    def __init__(self, sandbox=False):
        """Initialize the eBay authentication manager"""
        self.sandbox_mode = sandbox
        self.settings = get_settings()

        # Initialize secure token manager
        self.token_manager = SecureTokenManager(sandbox=sandbox)

        # Determine which credentials to use
        if sandbox:
            self.client_id = self.settings.EBAY_SANDBOX_CLIENT_ID
            self.dev_id = self.settings.EBAY_SANDBOX_DEV_ID
            self.client_secret = self.settings.EBAY_SANDBOX_CLIENT_SECRET
            self.ru_name = self.settings.EBAY_SANDBOX_RU_NAME
            self.auth_url = "https://auth.sandbox.ebay.com/oauth2/authorize"
            self.token_refresh_url = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
        else:
            self.client_id = self.settings.EBAY_CLIENT_ID
            self.dev_id = self.settings.EBAY_DEV_ID
            self.client_secret = self.settings.EBAY_CLIENT_SECRET
            self.ru_name = self.settings.EBAY_RU_NAME
            self.auth_url = "https://auth.ebay.com/oauth2/authorize"
            self.token_refresh_url = "https://api.ebay.com/identity/v1/oauth2/token"

        # Verify required credentials
        if not self.client_id or not self.client_secret:
            raise ValueError(
                f"Missing required eBay {'sandbox' if sandbox else 'production'} credentials. "
                f"Please check your .env file."
            )

        # Set scopes
        self.scopes = ["https://api.ebay.com/oauth/api_scope/sell.inventory"]

        logger.debug(f"EbayAuthManager initialized. Sandbox: {sandbox}")

    async def get_access_token(self) -> str:
        """
        Get a valid access token, refreshing if necessary
        """
        # Check if we have a valid token in memory
        access_token = self.token_manager.get_access_token()

        if access_token:
            logger.debug("Using cached access token from memory")
            return access_token

        # Need to refresh the token
        logger.info("No valid access token in memory, refreshing...")

        try:
            # Get refresh token from environment
            refresh_token = self.token_manager.get_refresh_token()
            if not refresh_token:
                raise EbayAPIError("No refresh token available")

            # Prepare refresh request
            refresh_data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token
            }

            auth = httpx.BasicAuth(self.client_id, self.client_secret)

            # Make refresh request
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.token_refresh_url,
                    data=refresh_data,
                    auth=auth
                )

            if response.status_code == 200:
                token_data = response.json()
                access_token = token_data['access_token']
                expires_in = token_data.get('expires_in', 7200)

                # Save to memory only (no file storage!)
                self.token_manager.save_access_token(access_token, expires_in)

                logger.info("Successfully refreshed access token")
                return access_token

            else:
                error_text = response.text
                logger.error(f"Token refresh failed: {error_text}")

                if "invalid_grant" in error_text:
                    raise EbayAPIError(
                        "Invalid refresh token. Please regenerate your eBay tokens."
                    )
                else:
                    raise EbayAPIError(f"Failed to refresh access token: {error_text}")

        except httpx.RequestError as e:
            logger.error(f"Network error refreshing token: {str(e)}")
            raise EbayAPIError(f"Network error refreshing access token: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error refreshing token: {str(e)}")
            raise

    def generate_user_authorization_url(self) -> str:
        """Generate the URL for user authorization"""
        if not self.ru_name:
            raise ValueError("RuName is required for authorization URL generation")

        auth_params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.ru_name,
            "scope": " ".join(self.scopes)
        }

        # Build URL with parameters
        param_string = "&".join([f"{k}={v}" for k, v in auth_params.items()])
        auth_url = f"{self.auth_url}?{param_string}"

        logger.info("Generated user authorization URL")
        return auth_url

    async def generate_refresh_token(self, authorization_code: str) -> Dict:
        """
        Exchange authorization code for refresh token
        Note: The refresh token should be immediately stored in environment variables
        """
        try:
            token_data = {
                "grant_type": "authorization_code",
                "code": authorization_code,
                "redirect_uri": self.ru_name
            }

            auth = httpx.BasicAuth(self.client_id, self.client_secret)

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.token_refresh_url,
                    data=token_data,
                    auth=auth
                )

            if response.status_code == 200:
                token_response = response.json()

                # Extract tokens
                access_token = token_response.get("access_token")
                refresh_token = token_response.get("refresh_token")
                expires_in = token_response.get("expires_in", 7200)
                refresh_token_expires_in = token_response.get("refresh_token_expires_in")

                # Save access token to memory
                if access_token:
                    self.token_manager.save_access_token(access_token, expires_in)

                # Calculate expiry
                days_until_expiry = int(refresh_token_expires_in / 86400) if refresh_token_expires_in else None

                logger.info(f"Successfully generated new refresh token")
                if days_until_expiry:
                    logger.info(f"Refresh token expires in {days_until_expiry} days")

                # Return token info for user to save
                return {
                    "refresh_token": refresh_token,
                    "refresh_token_expires_in_days": days_until_expiry,
                    "message": "IMPORTANT: Save the refresh_token to your .env file as EBAY_REFRESH_TOKEN"
                }

            else:
                error_text = response.text
                logger.error(f"Failed to generate refresh token: {error_text}")
                raise EbayAPIError(f"Failed to generate refresh token: {error_text}")

        except Exception as e:
            logger.error(f"Error generating refresh token: {str(e)}")
            raise

    def get_basic_auth_header(self) -> Dict[str, str]:
        """Get Basic authentication header for certain eBay APIs"""
        credentials = f"{self.client_id}:{self.client_secret}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        return {"Authorization": f"Basic {encoded_credentials}"}

    def check_refresh_token_expiry(self) -> tuple[bool, int]:
        """
        Check if refresh token is expiring soon
        Note: This is a placeholder - actual implementation would need to track
        when the refresh token was generated
        """
        # For now, always return that token is valid
        # In production, you'd track refresh token generation date
        return False, 365  # Not expiring, 365 days left

    def clear_tokens(self):
        """Clear all tokens from memory"""
        self.token_manager.clear_tokens()
        logger.info("Cleared all tokens from memory")