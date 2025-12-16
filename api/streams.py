"""Stream management API endpoints."""

import asyncio
import json
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Request, Query
from pydantic import BaseModel, Field

from config import settings
from database import db, Stream, StreamMode, StreamStatus, LatencyMode
from core.stream_analyzer import analyzer
from core.ffmpeg_builder import ffmpeg_builder
from core.stream_manager import stream_manager
from api.auth import require_auth, create_stream_token, verify_stream_access

router = APIRouter(prefix="/api/streams", tags=["streams"])


# Request/Response models
class StreamCreate(BaseModel):
    """Request model for creating a stream."""
    name: str = Field(..., min_length=1, max_length=100)
    rtsp_url: str = Field(..., min_length=10)
    mode: str = Field(default="on_demand", pattern="^(always_on|on_demand|smart)$")
    keep_alive_seconds: int = Field(default=60, ge=10, le=3600)
    use_transcode: bool = False
    latency_mode: str = Field(default="stable", pattern="^(low|stable)$")
    ffmpeg_overrides: Optional[dict] = None
    group_name: Optional[str] = Field(None, max_length=100)


class StreamUpdate(BaseModel):
    """Request model for updating a stream."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    rtsp_url: Optional[str] = Field(None, min_length=10)
    mode: Optional[str] = Field(None, pattern="^(always_on|on_demand|smart)$")
    keep_alive_seconds: Optional[int] = Field(None, ge=10, le=3600)
    use_transcode: Optional[bool] = None
    latency_mode: Optional[str] = Field(None, pattern="^(low|stable)$")
    ffmpeg_overrides: Optional[dict] = None
    group_name: Optional[str] = Field(None, max_length=100)


class StreamResponse(BaseModel):
    """Response model for stream data."""
    id: str
    name: str
    rtsp_url: str
    mode: str
    status: str
    video_codec: Optional[str]
    audio_codec: Optional[str]
    resolution: Optional[str]
    framerate: Optional[float]
    bitrate: Optional[int]
    viewer_count: int
    last_error: Optional[str]
    keep_alive_seconds: int
    use_transcode: bool
    latency_mode: str
    ffmpeg_overrides: Optional[dict]
    group_name: Optional[str]
    thumbnail: Optional[str]
    thumbnail_updated: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]
    hls_url: Optional[str] = None
    is_running: bool = False

    @classmethod
    def from_stream(cls, stream: Stream, base_url: str = "") -> "StreamResponse":
        overrides = None
        if stream.ffmpeg_overrides:
            try:
                overrides = json.loads(stream.ffmpeg_overrides)
            except json.JSONDecodeError:
                pass

        return cls(
            id=stream.id,
            name=stream.name,
            rtsp_url=stream.rtsp_url,
            mode=stream.mode,
            status=stream.status,
            video_codec=stream.video_codec,
            audio_codec=stream.audio_codec,
            resolution=stream.resolution,
            framerate=stream.framerate,
            bitrate=stream.bitrate,
            viewer_count=stream.viewer_count,
            last_error=stream.last_error,
            keep_alive_seconds=stream.keep_alive_seconds,
            use_transcode=bool(stream.use_transcode),
            latency_mode=stream.latency_mode or "stable",
            ffmpeg_overrides=overrides,
            group_name=stream.group_name,
            thumbnail=stream.thumbnail,
            thumbnail_updated=stream.thumbnail_updated,
            created_at=stream.created_at,
            updated_at=stream.updated_at,
            hls_url=f"{base_url}/hls/{stream.id}/stream.m3u8" if base_url else None,
            is_running=stream_manager.is_running(stream.id)
        )


class AnalyzeResponse(BaseModel):
    """Response model for stream analysis."""
    is_valid: bool
    error: Optional[str]
    video_codec: Optional[str]
    video_codec_name: Optional[str]
    resolution: Optional[str]
    framerate: Optional[float]
    video_bitrate: Optional[int]
    audio_codec: Optional[str]
    audio_codec_name: Optional[str]
    sample_rate: Optional[int]
    channels: Optional[int]
    can_copy_video: bool
    can_copy_audio: bool
    needs_transcode: bool
    transcode_reason: Optional[str]
    recommended_settings: dict


class TokenResponse(BaseModel):
    """Response model for stream token."""
    token: str
    expires_hours: int
    hls_url: str
    player_url: str


class StatusResponse(BaseModel):
    """Response model for stream status."""
    stream_id: str
    running: bool
    status: str
    viewer_count: int
    start_time: Optional[str]
    pid: Optional[int]
    reconnect_count: int = 0


class OverridesResponse(BaseModel):
    """Response model for FFmpeg override options."""
    options: dict
    description: dict


class PaginatedStreamsResponse(BaseModel):
    """Response model for paginated streams."""
    streams: List[StreamResponse]
    total: int
    page: int
    per_page: int
    total_pages: int
    counts: dict


class BatchRequest(BaseModel):
    """Request model for batch operations."""
    stream_ids: List[str] = Field(..., min_length=1, max_length=100)


class BatchResponse(BaseModel):
    """Response model for batch operations."""
    success: List[str]
    failed: List[dict]
    message: str


# Endpoints
# IMPORTANT: Static routes must be defined BEFORE parameterized routes
# to prevent /{stream_id} from catching paths like /batch or /overrides/options

@router.get("", response_model=PaginatedStreamsResponse)
async def list_streams(
    request: Request,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    search: str = Query(default=None, max_length=100),
    status: str = Query(default=None, pattern="^(stopped|starting|running|error|reconnecting)$"),
    mode: str = Query(default=None, pattern="^(always_on|on_demand|smart)$"),
    group: str = Query(default=None, max_length=100),
    sort_by: str = Query(default="id", pattern="^(id|name|status|mode|created_at|updated_at|viewer_count)$"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
    _=Depends(require_auth)
):
    """List streams with pagination, search, and filters."""
    streams, total = await db.get_streams_paginated(
        page=page,
        per_page=per_page,
        search=search,
        status=status,
        mode=mode,
        group=group,
        sort_by=sort_by,
        sort_order=sort_order
    )
    counts = await db.get_stream_counts()
    base_url = str(request.base_url).rstrip("/")

    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    return PaginatedStreamsResponse(
        streams=[StreamResponse.from_stream(s, base_url) for s in streams],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        counts=counts
    )


@router.post("", response_model=StreamResponse, status_code=201)
async def create_stream(
    data: StreamCreate,
    request: Request,
    _=Depends(require_auth)
):
    """Create a new stream."""
    # Check if URL already exists
    existing = await db.get_stream_by_url(data.rtsp_url)
    if existing:
        raise HTTPException(status_code=400, detail="Stream with this RTSP URL already exists")

    # Check max streams
    all_streams = await db.get_all_streams()
    if len(all_streams) >= settings.max_streams:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum number of streams ({settings.max_streams}) reached"
        )

    # Create stream
    stream = Stream(
        name=data.name,
        rtsp_url=data.rtsp_url,
        mode=data.mode,
        keep_alive_seconds=data.keep_alive_seconds,
        use_transcode=data.use_transcode,
        latency_mode=data.latency_mode,
        ffmpeg_overrides=json.dumps(data.ffmpeg_overrides) if data.ffmpeg_overrides else None,
        group_name=data.group_name
    )

    stream = await db.add_stream(stream)

    # Capture initial thumbnail in background
    asyncio.create_task(stream_manager.capture_stream_thumbnail(stream.id))

    # Auto-start if always_on
    if stream.mode == StreamMode.ALWAYS_ON.value:
        await stream_manager.start_stream(stream.id)

    base_url = str(request.base_url).rstrip("/")
    return StreamResponse.from_stream(stream, base_url)


# Static path routes - must come before /{stream_id} routes

@router.get("/overrides/options", response_model=OverridesResponse)
async def get_override_options(
    _=Depends(require_auth)
):
    """Get available FFmpeg override options."""
    options = ffmpeg_builder.get_default_overrides()

    descriptions = {
        "rtsp_transport": "RTSP transport protocol: tcp (reliable) or udp (lower latency)",
        "buffer_size": "Input buffer size in bytes (default: 1MB)",
        "timeout": "Connection timeout in microseconds (default: 5000000 = 5s)",
        "transcode_video": "Force video transcoding even if copy is possible",
        "transcode_audio": "Force audio transcoding even if copy is possible",
        "no_audio": "Disable audio completely",
        "preset": "x264 preset: ultrafast, superfast, veryfast, faster, fast, medium",
        "tune": "x264 tune: zerolatency (live), film, animation, grain",
        "profile": "x264 profile: baseline, main, high",
        "crf": "Quality (0-51, lower=better quality, 23=default)",
        "video_bitrate": "Target video bitrate (e.g., '2M', '4000k')",
        "audio_bitrate": "Target audio bitrate (e.g., '128k', '192k')",
        "audio_channels": "Number of audio channels (1=mono, 2=stereo)",
        "scale": "Scale video (e.g., '1280:720', '-1:480' for auto-width)",
        "hls_time": "HLS segment duration in seconds",
        "hls_list_size": "Number of segments in playlist",
        "hls_flags": "HLS flags (advanced)",
        "input_args": "Additional FFmpeg input arguments (array)",
        "video_args": "Additional FFmpeg video arguments (array)",
        "audio_args": "Additional FFmpeg audio arguments (array)",
        "output_args": "Additional FFmpeg output arguments (array)",
    }

    return OverridesResponse(options=options, description=descriptions)


# Batch operations - must come before /{stream_id} routes

@router.post("/batch/start", response_model=BatchResponse)
async def batch_start_streams(
    data: BatchRequest,
    _=Depends(require_auth)
):
    """Start multiple streams at once."""
    success = []
    failed = []

    for stream_id in data.stream_ids:
        try:
            stream = await db.get_stream(stream_id)
            if not stream:
                failed.append({"id": stream_id, "error": "Stream not found"})
                continue

            if stream_manager.is_running(stream_id):
                failed.append({"id": stream_id, "error": "Already running"})
                continue

            result = await stream_manager.start_stream(stream_id)
            if result:
                success.append(stream_id)
            else:
                stream = await db.get_stream(stream_id)
                failed.append({"id": stream_id, "error": stream.last_error or "Failed to start"})
        except Exception as e:
            failed.append({"id": stream_id, "error": str(e)})

    return BatchResponse(
        success=success,
        failed=failed,
        message=f"Started {len(success)} streams, {len(failed)} failed"
    )


@router.post("/batch/stop", response_model=BatchResponse)
async def batch_stop_streams(
    data: BatchRequest,
    _=Depends(require_auth)
):
    """Stop multiple streams at once."""
    success = []
    failed = []

    for stream_id in data.stream_ids:
        try:
            stream = await db.get_stream(stream_id)
            if not stream:
                failed.append({"id": stream_id, "error": "Stream not found"})
                continue

            if not stream_manager.is_running(stream_id):
                failed.append({"id": stream_id, "error": "Not running"})
                continue

            await stream_manager.stop_stream(stream_id)
            success.append(stream_id)
        except Exception as e:
            failed.append({"id": stream_id, "error": str(e)})

    return BatchResponse(
        success=success,
        failed=failed,
        message=f"Stopped {len(success)} streams, {len(failed)} failed"
    )


@router.post("/batch/restart", response_model=BatchResponse)
async def batch_restart_streams(
    data: BatchRequest,
    _=Depends(require_auth)
):
    """Restart multiple streams at once."""
    success = []
    failed = []

    for stream_id in data.stream_ids:
        try:
            stream = await db.get_stream(stream_id)
            if not stream:
                failed.append({"id": stream_id, "error": "Stream not found"})
                continue

            # Stop if running
            if stream_manager.is_running(stream_id):
                await stream_manager.stop_stream(stream_id)

            # Start
            result = await stream_manager.start_stream(stream_id)
            if result:
                success.append(stream_id)
            else:
                stream = await db.get_stream(stream_id)
                failed.append({"id": stream_id, "error": stream.last_error or "Failed to start"})
        except Exception as e:
            failed.append({"id": stream_id, "error": str(e)})

    return BatchResponse(
        success=success,
        failed=failed,
        message=f"Restarted {len(success)} streams, {len(failed)} failed"
    )


@router.delete("/batch", response_model=BatchResponse)
async def batch_delete_streams(
    data: BatchRequest,
    _=Depends(require_auth)
):
    """Delete multiple streams at once."""
    success = []
    failed = []

    for stream_id in data.stream_ids:
        try:
            stream = await db.get_stream(stream_id)
            if not stream:
                failed.append({"id": stream_id, "error": "Stream not found"})
                continue

            # Stop if running
            if stream_manager.is_running(stream_id):
                await stream_manager.stop_stream(stream_id)

            await db.delete_stream(stream_id)
            success.append(stream_id)
        except Exception as e:
            failed.append({"id": stream_id, "error": str(e)})

    return BatchResponse(
        success=success,
        failed=failed,
        message=f"Deleted {len(success)} streams, {len(failed)} failed"
    )


# Parameterized routes - must come AFTER static routes

@router.get("/{stream_id}", response_model=StreamResponse)
async def get_stream(
    stream_id: str,
    request: Request,
    _=Depends(require_auth)
):
    """Get a specific stream."""
    stream = await db.get_stream(stream_id)
    if not stream:
        raise HTTPException(status_code=404, detail="Stream not found")

    base_url = str(request.base_url).rstrip("/")
    return StreamResponse.from_stream(stream, base_url)


@router.put("/{stream_id}", response_model=StreamResponse)
async def update_stream(
    stream_id: str,
    data: StreamUpdate,
    request: Request,
    _=Depends(require_auth)
):
    """Update a stream."""
    stream = await db.get_stream(stream_id)
    if not stream:
        raise HTTPException(status_code=404, detail="Stream not found")

    # Check if RTSP URL changed and is unique
    if data.rtsp_url and data.rtsp_url != stream.rtsp_url:
        existing = await db.get_stream_by_url(data.rtsp_url)
        if existing:
            raise HTTPException(status_code=400, detail="Stream with this RTSP URL already exists")
        stream.rtsp_url = data.rtsp_url
        # Clear detected settings if URL changed
        stream.video_codec = None
        stream.audio_codec = None
        stream.resolution = None
        stream.framerate = None
        stream.bitrate = None

    # Update fields
    if data.name is not None:
        stream.name = data.name
    if data.mode is not None:
        stream.mode = data.mode
    if data.keep_alive_seconds is not None:
        stream.keep_alive_seconds = data.keep_alive_seconds
    if data.use_transcode is not None:
        stream.use_transcode = data.use_transcode
    if data.latency_mode is not None:
        stream.latency_mode = data.latency_mode
    if data.ffmpeg_overrides is not None:
        stream.ffmpeg_overrides = json.dumps(data.ffmpeg_overrides)
    if data.group_name is not None:
        stream.group_name = data.group_name if data.group_name else None

    await db.update_stream(stream)

    # Restart if running and settings changed
    if stream_manager.is_running(stream_id):
        await stream_manager.stop_stream(stream_id)
        await stream_manager.start_stream(stream_id)

    base_url = str(request.base_url).rstrip("/")
    return StreamResponse.from_stream(stream, base_url)


@router.delete("/{stream_id}", status_code=204)
async def delete_stream(
    stream_id: str,
    _=Depends(require_auth)
):
    """Delete a stream."""
    stream = await db.get_stream(stream_id)
    if not stream:
        raise HTTPException(status_code=404, detail="Stream not found")

    # Stop if running
    if stream_manager.is_running(stream_id):
        await stream_manager.stop_stream(stream_id)

    # Delete from database
    await db.delete_stream(stream_id)


@router.post("/{stream_id}/analyze", response_model=AnalyzeResponse)
async def analyze_stream(
    stream_id: str,
    _=Depends(require_auth)
):
    """Analyze stream properties using ffprobe."""
    stream = await db.get_stream(stream_id)
    if not stream:
        raise HTTPException(status_code=404, detail="Stream not found")

    info = await analyzer.analyze(stream.rtsp_url)

    # Update stream with detected info
    if info.is_valid:
        stream.video_codec = info.video_codec
        stream.audio_codec = info.audio_codec
        stream.resolution = info.resolution
        stream.framerate = info.framerate
        stream.bitrate = info.video_bitrate
        await db.update_stream(stream)

    # Build recommended settings
    recommended = {}
    if info.needs_transcode:
        recommended["use_transcode"] = True
        recommended["preset"] = "ultrafast"
        recommended["tune"] = "zerolatency"
    else:
        recommended["use_transcode"] = False

    if not info.can_copy_audio and info.audio_codec:
        recommended["transcode_audio"] = True

    return AnalyzeResponse(
        is_valid=info.is_valid,
        error=info.error,
        video_codec=info.video_codec,
        video_codec_name=info.video_codec_name,
        resolution=info.resolution,
        framerate=info.framerate,
        video_bitrate=info.video_bitrate,
        audio_codec=info.audio_codec,
        audio_codec_name=info.audio_codec_name,
        sample_rate=info.sample_rate,
        channels=info.channels,
        can_copy_video=info.can_copy_video,
        can_copy_audio=info.can_copy_audio,
        needs_transcode=info.needs_transcode,
        transcode_reason=info.transcode_reason,
        recommended_settings=recommended
    )


@router.post("/{stream_id}/start", response_model=StatusResponse)
async def start_stream(
    stream_id: str,
    _=Depends(require_auth)
):
    """Manually start a stream."""
    stream = await db.get_stream(stream_id)
    if not stream:
        raise HTTPException(status_code=404, detail="Stream not found")

    if stream_manager.is_running(stream_id):
        raise HTTPException(status_code=400, detail="Stream already running")

    success = await stream_manager.start_stream(stream_id)
    if not success:
        # Refresh stream to get error
        stream = await db.get_stream(stream_id)
        raise HTTPException(
            status_code=500,
            detail=stream.last_error or "Failed to start stream"
        )

    status = stream_manager.get_stream_status(stream_id)
    return StatusResponse(stream_id=stream_id, **status)


@router.post("/{stream_id}/stop", response_model=StatusResponse)
async def stop_stream(
    stream_id: str,
    _=Depends(require_auth)
):
    """Manually stop a stream."""
    stream = await db.get_stream(stream_id)
    if not stream:
        raise HTTPException(status_code=404, detail="Stream not found")

    if not stream_manager.is_running(stream_id):
        raise HTTPException(status_code=400, detail="Stream not running")

    await stream_manager.stop_stream(stream_id)

    status = stream_manager.get_stream_status(stream_id)
    return StatusResponse(stream_id=stream_id, **status)


@router.get("/{stream_id}/status", response_model=StatusResponse)
async def get_stream_status(
    stream_id: str,
    _=Depends(require_auth)
):
    """Get current stream status."""
    stream = await db.get_stream(stream_id)
    if not stream:
        raise HTTPException(status_code=404, detail="Stream not found")

    status = stream_manager.get_stream_status(stream_id)
    return StatusResponse(stream_id=stream_id, **status)


@router.get("/{stream_id}/token", response_model=TokenResponse)
async def get_stream_token(
    stream_id: str,
    request: Request,
    expires_hours: int = Query(default=24, ge=1, le=168),
    bind_ip: bool = Query(default=False),
    _=Depends(require_auth)
):
    """Generate a playback token for a stream."""
    stream = await db.get_stream(stream_id)
    if not stream:
        raise HTTPException(status_code=404, detail="Stream not found")

    client_ip = request.client.host if bind_ip and request.client else None
    token = create_stream_token(stream_id, expires_hours, client_ip)

    base_url = str(request.base_url).rstrip("/")
    return TokenResponse(
        token=token,
        expires_hours=expires_hours,
        hls_url=f"{base_url}/hls/{stream_id}/stream.m3u8?token={token}",
        player_url=f"{base_url}/?stream={stream_id}&token={token}"
    )


@router.post("/{stream_id}/heartbeat")
async def viewer_heartbeat(
    stream_id: str,
    request: Request,
    viewer_id: str = Depends(verify_stream_access)
):
    """Register viewer heartbeat (keeps on-demand stream alive)."""
    stream = await db.get_stream(stream_id)
    if not stream:
        raise HTTPException(status_code=404, detail="Stream not found")

    running = await stream_manager.viewer_heartbeat(stream_id, viewer_id)

    return {
        "status": "ok",
        "running": running,
        "viewer_id": viewer_id
    }


@router.post("/{stream_id}/snapshot")
async def capture_snapshot(
    stream_id: str,
    _=Depends(require_auth)
):
    """Capture a snapshot/thumbnail from the stream."""
    stream = await db.get_stream(stream_id)
    if not stream:
        raise HTTPException(status_code=404, detail="Stream not found")

    thumbnail = await stream_manager.capture_stream_thumbnail(stream_id)
    if not thumbnail:
        raise HTTPException(status_code=500, detail="Failed to capture snapshot")

    return {
        "status": "ok",
        "thumbnail": thumbnail,
        "stream_id": stream_id
    }


@router.post("/batch/refresh-thumbnails")
async def refresh_all_thumbnails(_=Depends(require_auth)):
    """Capture thumbnails for all streams (runs in background)."""
    streams = await db.get_all_streams()

    async def capture_all():
        success = 0
        failed = 0
        for stream in streams:
            try:
                thumbnail = await stream_manager.capture_stream_thumbnail(stream.id)
                if thumbnail:
                    success += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
            # Small delay between captures to avoid overwhelming
            await asyncio.sleep(0.5)
        return success, failed

    # Run in background
    asyncio.create_task(capture_all())

    return {
        "status": "ok",
        "message": f"Refreshing thumbnails for {len(streams)} streams in background"
    }


@router.get("/groups/list")
async def get_groups(_=Depends(require_auth)):
    """Get all unique group names."""
    groups = await db.get_groups()
    return {"groups": groups}
