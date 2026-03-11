from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from typing import Annotated
import secrets
from app.core.config import get_settings

security = HTTPBasic()
settings = get_settings()

def verify_credentials(credentials: Annotated[HTTPBasicCredentials, Depends(security)]):
    """Basic auth for now - replace with proper auth later"""
    # Get username/password from environment variables
    correct_username = settings.ADMIN_USERNAME if hasattr(settings, 'ADMIN_USERNAME') else "admin"
    correct_password = settings.ADMIN_PASSWORD if hasattr(settings, 'ADMIN_PASSWORD') else "changeme"
    
    current_username_bytes = credentials.username.encode("utf8")
    correct_username_bytes = correct_username.encode("utf8")
    is_correct_username = secrets.compare_digest(
        current_username_bytes, correct_username_bytes
    )
    current_password_bytes = credentials.password.encode("utf8")
    correct_password_bytes = correct_password.encode("utf8")
    is_correct_password = secrets.compare_digest(
        current_password_bytes, correct_password_bytes
    )
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username