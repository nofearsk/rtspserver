"""Authentication and authorization for the API."""

import jwt
import secrets
from datetime import datetime, timedelta
from typing import Optional
from fastapi import HTTPException, Security, Depends, Request, Cookie, Response
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials

from config import settings
from database import db, User

# API Key header
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Bearer token for stream access
bearer_scheme = HTTPBearer(auto_error=False)

# Session cookie name
SESSION_COOKIE = "session_token"


async def get_current_user(
    request: Request,
    session_token: str = Cookie(default=None, alias=SESSION_COOKIE),
    api_key: str = Security(api_key_header)
) -> Optional[User]:
    """Get current user from session cookie or API key."""
    # Try session cookie first (for web UI)
    if session_token:
        user = await db.get_user_by_session(session_token)
        if user:
            return user

    # Try API key (for external API access)
    if api_key:
        api_key_obj = await db.verify_api_key(api_key)
        if api_key_obj:
            # Return a pseudo-user for API key access
            return User(id=0, username=f"api:{api_key_obj.name}", is_admin=True)

    return None


async def require_auth(
    request: Request,
    session_token: str = Cookie(default=None, alias=SESSION_COOKIE),
    api_key: str = Security(api_key_header)
) -> User:
    """Require authentication - either session or API key."""
    user = await get_current_user(request, session_token, api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


async def verify_api_key(api_key: str = Security(api_key_header)) -> bool:
    """Verify API key for management endpoints (legacy support)."""
    if not api_key:
        raise HTTPException(status_code=401, detail="API key required")

    api_key_obj = await db.verify_api_key(api_key)
    if not api_key_obj:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return True


def create_stream_token(
    stream_id: str,
    expires_hours: int = None,
    client_ip: str = None
) -> str:
    """
    Create a JWT token for stream access.

    Args:
        stream_id: ID of the stream (string UID)
        expires_hours: Token expiry in hours (default from settings)
        client_ip: Optional client IP to bind token to

    Returns:
        JWT token string
    """
    if expires_hours is None:
        expires_hours = settings.token_expiry_hours

    payload = {
        "stream_id": stream_id,
        "exp": datetime.utcnow() + timedelta(hours=expires_hours),
        "iat": datetime.utcnow(),
        "jti": secrets.token_hex(8),  # Unique token ID
    }

    if client_ip:
        payload["ip"] = client_ip

    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def verify_stream_token(token: str, stream_id: str, client_ip: str = None) -> bool:
    """
    Verify a stream access token.

    Args:
        token: JWT token string
        stream_id: Expected stream ID (string UID)
        client_ip: Client IP to verify (if token was IP-bound)

    Returns:
        True if valid

    Raises:
        HTTPException if invalid
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])

        # Verify stream ID
        if payload.get("stream_id") != stream_id:
            raise HTTPException(status_code=403, detail="Token not valid for this stream")

        # Verify IP if bound
        if "ip" in payload and client_ip and payload["ip"] != client_ip:
            raise HTTPException(status_code=403, detail="Token not valid for this IP")

        return True

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


def get_token_from_query_or_header(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)
) -> Optional[str]:
    """Extract token from query param or Authorization header."""
    # Try query parameter first (for HLS playback)
    token = request.query_params.get("token")
    if token:
        return token

    # Try Authorization header
    if credentials:
        return credentials.credentials

    return None


async def verify_stream_access(
    stream_id: str,
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)
) -> str:
    """
    Verify access to a stream.

    Returns viewer_id for tracking.
    """
    token = get_token_from_query_or_header(request, credentials)

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Stream token required. Get one from /api/streams/{id}/token"
        )

    client_ip = request.client.host if request.client else None
    verify_stream_token(token, stream_id, client_ip)

    # Use token's jti as viewer ID, or generate one
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        return payload.get("jti", secrets.token_hex(8))
    except jwt.InvalidTokenError:
        return secrets.token_hex(8)


def generate_viewer_id() -> str:
    """Generate a unique viewer ID."""
    return secrets.token_hex(8)


def set_session_cookie(response: Response, token: str, max_age: int = 86400 * 7):
    """Set session cookie on response."""
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=False  # Set to True in production with HTTPS
    )


def clear_session_cookie(response: Response):
    """Clear session cookie."""
    response.delete_cookie(key=SESSION_COOKIE)
