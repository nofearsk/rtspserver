"""Settings API endpoints."""

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from database import db
from api.auth import require_auth

router = APIRouter(prefix="/api/settings", tags=["settings"])


# Request/Response models
class ClaudeApiKeyRequest(BaseModel):
    """Request model for setting Claude API key."""
    api_key: str = Field(..., min_length=10, description="Claude API key")


class ClaudeApiKeyResponse(BaseModel):
    """Response model for Claude API key status."""
    configured: bool
    key_preview: Optional[str] = None  # First/last few chars for verification


class SettingsResponse(BaseModel):
    """Response model for settings."""
    claude_api_configured: bool


# Endpoints

@router.get("", response_model=SettingsResponse)
async def get_settings(_=Depends(require_auth)):
    """Get current settings status."""
    claude_key = await db.get_setting("claude_api_key")
    return SettingsResponse(
        claude_api_configured=bool(claude_key)
    )


@router.get("/claude-api", response_model=ClaudeApiKeyResponse)
async def get_claude_api_status(_=Depends(require_auth)):
    """Check if Claude API key is configured."""
    api_key = await db.get_setting("claude_api_key")
    if api_key:
        # Show preview: first 8 and last 4 chars
        preview = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "***"
        return ClaudeApiKeyResponse(configured=True, key_preview=preview)
    return ClaudeApiKeyResponse(configured=False)


@router.post("/claude-api")
async def set_claude_api_key(
    data: ClaudeApiKeyRequest,
    _=Depends(require_auth)
):
    """Set Claude API key."""
    # Basic validation
    if not data.api_key.startswith("sk-"):
        raise HTTPException(
            status_code=400,
            detail="Invalid API key format. Claude API keys start with 'sk-'"
        )

    # Store the key
    await db.set_setting("claude_api_key", data.api_key)

    return {
        "status": "ok",
        "message": "Claude API key saved successfully"
    }


@router.delete("/claude-api")
async def delete_claude_api_key(_=Depends(require_auth)):
    """Remove Claude API key."""
    await db.delete_setting("claude_api_key")
    return {"status": "ok", "message": "Claude API key removed"}
