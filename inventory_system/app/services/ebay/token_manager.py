"""
Secure token management for eBay API
Stores access tokens in memory only, never persists to disk
"""

import os
from datetime import datetime, timedelta
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)


class SecureTokenManager:
    """
    Manages eBay tokens securely:
    - Refresh token: ALWAYS from environment variables
    - Access token: Stored in memory only (never persisted to disk)
    """

    # Class-level storage for access tokens (shared across instances)
    _access_tokens: Dict[str, Dict] = {}

    def __init__(self, sandbox: bool = False):
        self.sandbox = sandbox
        self.env_prefix = "EBAY_SANDBOX_" if sandbox else "EBAY_"

        # Always get refresh token from environment
        self.refresh_token = os.getenv(f"{self.env_prefix}REFRESH_TOKEN")
        if not self.refresh_token:
            raise ValueError(f"Missing {self.env_prefix}REFRESH_TOKEN environment variable")

    def get_access_token(self) -> Optional[str]:
        """Get access token from memory if valid"""
        key = "sandbox" if self.sandbox else "production"
        token_data = self._access_tokens.get(key, {})

        access_token = token_data.get("access_token")
        expires_at_str = token_data.get("expires_at")

        if access_token and expires_at_str:
            try:
                expires_at = datetime.fromisoformat(expires_at_str)
                # Add 5 minute buffer
                if datetime.now() < (expires_at - timedelta(minutes=5)):
                    logger.debug(f"Returning valid access token from memory (expires: {expires_at})")
                    return access_token
                else:
                    logger.debug("Access token expired or expiring soon")
            except ValueError:
                logger.error(f"Invalid expires_at format: {expires_at_str}")

        return None

    def save_access_token(self, access_token: str, expires_in: int):
        """Save access token to memory only"""
        key = "sandbox" if self.sandbox else "production"
        expires_at = datetime.now() + timedelta(seconds=expires_in)

        self._access_tokens[key] = {
            "access_token": access_token,
            "expires_at": expires_at.isoformat(),
            "expires_in": expires_in
        }

        logger.info(f"Saved access token to memory (expires: {expires_at})")

    def get_refresh_token(self) -> str:
        """Always returns refresh token from environment"""
        return self.refresh_token

    def clear_tokens(self):
        """Clear access tokens from memory"""
        key = "sandbox" if self.sandbox else "production"
        if key in self._access_tokens:
            del self._access_tokens[key]
            logger.info("Cleared access token from memory")


# Optional: Function to clear all tokens (useful for testing)
def clear_all_tokens():
    """Clear all tokens from memory"""
    SecureTokenManager._access_tokens.clear()
    logger.info("Cleared all access tokens from memory")