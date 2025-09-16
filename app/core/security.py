"""
Basic security implementation for the inventory system
"""

import secrets
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic()


def get_current_username(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    """
    Simple HTTP Basic Auth - checks username/password from environment variables
    """
    import os

    # Get credentials from environment
    correct_username = os.getenv("BASIC_AUTH_USERNAME", "admin")
    correct_password = os.getenv("BASIC_AUTH_PASSWORD", None)

    # If no password is set in production, raise an error
    if not correct_password and os.getenv("RAILWAY_ENVIRONMENT"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Basic auth password not configured"
        )

    # In development, allow a default password
    if not correct_password:
        correct_password = "changeme"

    # Verify credentials
    is_correct_username = secrets.compare_digest(
        credentials.username.encode("utf8"),
        correct_username.encode("utf8")
    )
    is_correct_password = secrets.compare_digest(
        credentials.password.encode("utf8"),
        correct_password.encode("utf8")
    )

    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username


# Optional: Create a dependency that can be easily added to routes
def require_auth():
    """
    Dependency to require authentication
    Usage: @router.get("/", dependencies=[Depends(require_auth)])
    """
    return Depends(get_current_username)