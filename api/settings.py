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


class ServerSettingsRequest(BaseModel):
    """Request model for server settings."""
    max_concurrent_streams: Optional[int] = Field(None, ge=1, le=100, description="Max concurrent streams (FIFO)")
    keep_alive_seconds: Optional[int] = Field(None, ge=10, le=3600, description="Keep stream alive after viewer leaves")
    segment_max_age_minutes: Optional[int] = Field(None, ge=1, le=60, description="Delete segments older than X minutes")
    hls_time: Optional[int] = Field(None, ge=1, le=10, description="HLS segment duration in seconds")
    hls_list_size: Optional[int] = Field(None, ge=3, le=20, description="Number of segments in playlist")


class ServerSettingsResponse(BaseModel):
    """Response model for server settings."""
    max_concurrent_streams: int = 30
    keep_alive_seconds: int = 60
    segment_max_age_minutes: int = 5
    hls_time: int = 2
    hls_list_size: int = 5


class SettingsResponse(BaseModel):
    """Response model for all settings."""
    claude_api_configured: bool
    server: ServerSettingsResponse


# Endpoints

@router.get("", response_model=SettingsResponse)
async def get_settings(_=Depends(require_auth)):
    """Get current settings status."""
    claude_key = await db.get_setting("claude_api_key")

    # Get server settings from database (with defaults from config)
    from config import settings as config_settings

    server_settings = ServerSettingsResponse(
        max_concurrent_streams=int(await db.get_setting("max_concurrent_streams") or config_settings.max_concurrent_streams),
        keep_alive_seconds=int(await db.get_setting("keep_alive_seconds") or config_settings.keep_alive_seconds),
        segment_max_age_minutes=int(await db.get_setting("segment_max_age_minutes") or config_settings.segment_max_age_minutes),
        hls_time=int(await db.get_setting("hls_time") or config_settings.hls_time),
        hls_list_size=int(await db.get_setting("hls_list_size") or config_settings.hls_list_size),
    )

    return SettingsResponse(
        claude_api_configured=bool(claude_key),
        server=server_settings
    )


@router.get("/server", response_model=ServerSettingsResponse)
async def get_server_settings(_=Depends(require_auth)):
    """Get server settings."""
    from config import settings as config_settings

    return ServerSettingsResponse(
        max_concurrent_streams=int(await db.get_setting("max_concurrent_streams") or config_settings.max_concurrent_streams),
        keep_alive_seconds=int(await db.get_setting("keep_alive_seconds") or config_settings.keep_alive_seconds),
        segment_max_age_minutes=int(await db.get_setting("segment_max_age_minutes") or config_settings.segment_max_age_minutes),
        hls_time=int(await db.get_setting("hls_time") or config_settings.hls_time),
        hls_list_size=int(await db.get_setting("hls_list_size") or config_settings.hls_list_size),
    )


@router.put("/server", response_model=ServerSettingsResponse)
async def update_server_settings(
    data: ServerSettingsRequest,
    _=Depends(require_auth)
):
    """Update server settings."""
    # Save each setting that was provided
    if data.max_concurrent_streams is not None:
        await db.set_setting("max_concurrent_streams", str(data.max_concurrent_streams))
    if data.keep_alive_seconds is not None:
        await db.set_setting("keep_alive_seconds", str(data.keep_alive_seconds))
    if data.segment_max_age_minutes is not None:
        await db.set_setting("segment_max_age_minutes", str(data.segment_max_age_minutes))
    if data.hls_time is not None:
        await db.set_setting("hls_time", str(data.hls_time))
    if data.hls_list_size is not None:
        await db.set_setting("hls_list_size", str(data.hls_list_size))

    # Return updated settings
    return await get_server_settings(_)


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
