"""
Basic security implementation for the inventory system

Supports multiple users via two methods:
1. Primary user: BASIC_AUTH_USERNAME and BASIC_AUTH_PASSWORD (your main login)
2. Additional users: BASIC_AUTH_USERS with format "user1:pass1,user2:pass2"

Railway Configuration Example:
------------------------------
BASIC_AUTH_USERNAME = adam
BASIC_AUTH_PASSWORD = your_main_password
BASIC_AUTH_USERS    = justin:justins_password,claire:claires_password

Note: No spaces around colons or commas. No quotes needed.
"""

import secrets
from typing import Optional, Dict
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic()


def _parse_additional_users(users_string: Optional[str]) -> Dict[str, str]:
    """
    Parse BASIC_AUTH_USERS environment variable.

    Format: "username1:password1,username2:password2"

    Example: "justin:secretpass,claire:anotherpass"

    Returns dict of {username: password}
    """
    if not users_string:
        return {}

    users = {}
    for pair in users_string.split(","):
        pair = pair.strip()
        if ":" in pair:
            username, password = pair.split(":", 1)  # Split on first colon only
            username = username.strip()
            password = password.strip()
            if username and password:
                users[username] = password
    return users


def get_current_username(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    """
    Simple HTTP Basic Auth - checks username/password from environment variables.

    Checks in order:
    1. Primary user (BASIC_AUTH_USERNAME / BASIC_AUTH_PASSWORD)
    2. Additional users (BASIC_AUTH_USERS = "user1:pass1,user2:pass2")
    """
    import os

    # Build dict of all valid users
    valid_users: Dict[str, str] = {}

    # 1. Add primary user from BASIC_AUTH_USERNAME/PASSWORD
    primary_username = os.getenv("BASIC_AUTH_USERNAME", "admin")
    primary_password = os.getenv("BASIC_AUTH_PASSWORD", None)

    # If no password is set in production, raise an error
    if not primary_password and os.getenv("RAILWAY_ENVIRONMENT"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Basic auth password not configured"
        )

    # In development, allow a default password
    if not primary_password:
        primary_password = "changeme"

    valid_users[primary_username] = primary_password

    # 2. Add additional users from BASIC_AUTH_USERS
    additional_users = _parse_additional_users(os.getenv("BASIC_AUTH_USERS"))
    valid_users.update(additional_users)

    # Check if the provided credentials match any valid user
    provided_username = credentials.username
    provided_password = credentials.password

    # Look up the user
    if provided_username not in valid_users:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )

    # Verify password using constant-time comparison
    is_correct_password = secrets.compare_digest(
        provided_password.encode("utf8"),
        valid_users[provided_username].encode("utf8")
    )

    if not is_correct_password:
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