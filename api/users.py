"""User authentication and API key management endpoints."""

import secrets
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Request, Response, Depends
from pydantic import BaseModel, Field

from database import db, User
from api.auth import (
    get_current_user, require_auth, set_session_cookie, clear_session_cookie
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# Request/Response models
class SetupRequest(BaseModel):
    """Request model for initial setup."""
    username: str = Field(default="admin", min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=100)


class LoginRequest(BaseModel):
    """Request model for login."""
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class ChangePasswordRequest(BaseModel):
    """Request model for changing password."""
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=100)


class ApiKeyCreate(BaseModel):
    """Request model for creating API key."""
    name: str = Field(..., min_length=1, max_length=100)


class ApiKeyResponse(BaseModel):
    """Response model for API key."""
    id: int
    name: str
    key_prefix: str
    created_at: Optional[str]
    last_used: Optional[str]


class ApiKeyCreatedResponse(BaseModel):
    """Response model for newly created API key (includes full key)."""
    id: int
    name: str
    key: str
    key_prefix: str
    created_at: Optional[str]


class UserResponse(BaseModel):
    """Response model for user info."""
    id: int
    username: str
    is_admin: bool


class AuthStatusResponse(BaseModel):
    """Response model for auth status."""
    setup_complete: bool
    authenticated: bool
    user: Optional[UserResponse] = None


# Endpoints

@router.get("/status", response_model=AuthStatusResponse)
async def get_auth_status(
    request: Request,
    user: Optional[User] = Depends(get_current_user)
):
    """Check authentication status and whether setup is complete."""
    setup_complete = await db.is_setup_complete()

    if user:
        return AuthStatusResponse(
            setup_complete=setup_complete,
            authenticated=True,
            user=UserResponse(
                id=user.id,
                username=user.username,
                is_admin=user.is_admin
            )
        )

    return AuthStatusResponse(
        setup_complete=setup_complete,
        authenticated=False
    )


@router.post("/setup")
async def initial_setup(data: SetupRequest, response: Response):
    """Initial setup - create admin user. Can only be called once."""
    if await db.is_setup_complete():
        raise HTTPException(status_code=400, detail="Setup already completed")

    # Create admin user
    user = await db.create_user(data.username, data.password, is_admin=True)

    # Create session and set cookie
    session = await db.create_session(user.id)
    set_session_cookie(response, session.token)

    return {
        "status": "ok",
        "message": "Setup complete",
        "user": UserResponse(
            id=user.id,
            username=user.username,
            is_admin=user.is_admin
        )
    }


@router.post("/login")
async def login(data: LoginRequest, response: Response):
    """Login with username and password."""
    if not await db.is_setup_complete():
        raise HTTPException(status_code=400, detail="Setup not complete")

    user = await db.verify_user(data.username, data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Create session and set cookie
    session = await db.create_session(user.id)
    set_session_cookie(response, session.token)

    return {
        "status": "ok",
        "user": UserResponse(
            id=user.id,
            username=user.username,
            is_admin=user.is_admin
        )
    }


@router.post("/logout")
async def logout(response: Response, user: User = Depends(require_auth)):
    """Logout current user."""
    clear_session_cookie(response)
    return {"status": "ok"}


@router.post("/change-password")
async def change_password(
    data: ChangePasswordRequest,
    user: User = Depends(require_auth)
):
    """Change current user's password."""
    # Verify current password
    verified = await db.verify_user(user.username, data.current_password)
    if not verified:
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    # Update password
    await db.update_user_password(user.id, data.new_password)

    return {"status": "ok", "message": "Password changed successfully"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(user: User = Depends(require_auth)):
    """Get current user info."""
    return UserResponse(
        id=user.id,
        username=user.username,
        is_admin=user.is_admin
    )


# API Key management

@router.get("/api-keys", response_model=List[ApiKeyResponse])
async def list_api_keys(user: User = Depends(require_auth)):
    """List all API keys."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    keys = await db.get_all_api_keys()
    return [
        ApiKeyResponse(
            id=key.id,
            name=key.name,
            key_prefix=key.key_prefix,
            created_at=key.created_at,
            last_used=key.last_used
        )
        for key in keys
    ]


@router.post("/api-keys", response_model=ApiKeyCreatedResponse)
async def create_api_key(data: ApiKeyCreate, user: User = Depends(require_auth)):
    """Create a new API key."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    api_key, raw_key = await db.create_api_key(data.name)

    return ApiKeyCreatedResponse(
        id=api_key.id,
        name=api_key.name,
        key=raw_key,  # Full key only returned once on creation
        key_prefix=api_key.key_prefix,
        created_at=api_key.created_at
    )


@router.delete("/api-keys/{key_id}", status_code=204)
async def delete_api_key(key_id: int, user: User = Depends(require_auth)):
    """Delete an API key."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    deleted = await db.delete_api_key(key_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="API key not found")
