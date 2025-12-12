"""NVR Discovery API endpoints."""

import asyncio
import json
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from database import db, Stream
from core.nvr_discovery import nvr_discovery, NVRBrand
from core.vision_analyzer import vision_analyzer
from api.auth import require_auth

router = APIRouter(prefix="/api/nvr", tags=["nvr"])


# Request/Response models
class NVRDiscoverRequest(BaseModel):
    """Request model for NVR discovery."""
    host: str = Field(..., min_length=1, description="NVR IP address or hostname")
    username: str = Field(..., min_length=1, description="Admin username")
    password: str = Field(..., min_length=1, description="Admin password")
    port: int = Field(default=80, ge=1, le=65535, description="HTTP port")
    rtsp_port: int = Field(default=554, ge=1, le=65535, description="RTSP port")
    brand: str = Field(default="auto", description="NVR brand or 'auto' for auto-detection")


class DiscoveredCameraResponse(BaseModel):
    """Response model for a discovered camera."""
    channel_id: int
    name: str
    rtsp_url_main: str
    rtsp_url_sub: Optional[str]
    resolution: Optional[str]
    status: str
    model: Optional[str]


class NVRDiscoverResponse(BaseModel):
    """Response model for NVR discovery."""
    brand: str
    model: Optional[str]
    serial: Optional[str]
    firmware: Optional[str]
    channels: int
    cameras: List[DiscoveredCameraResponse]
    error: Optional[str]


class CameraImportRequest(BaseModel):
    """Request model for importing cameras."""
    cameras: List[dict] = Field(..., description="List of cameras to import")
    mode: str = Field(default="on_demand", pattern="^(always_on|on_demand|smart)$")
    latency_mode: str = Field(default="stable", pattern="^(low|stable)$")
    use_sub_stream: bool = Field(default=False, description="Use sub-stream instead of main")


class ImportResult(BaseModel):
    """Result of importing a single camera."""
    channel_id: int
    name: str
    success: bool
    stream_id: Optional[str]
    error: Optional[str]


class CameraImportResponse(BaseModel):
    """Response model for camera import."""
    total: int
    imported: int
    failed: int
    results: List[ImportResult]


class BrandsResponse(BaseModel):
    """Response model for supported brands."""
    brands: List[dict]


class AnalyzeFrameRequest(BaseModel):
    """Request model for frame analysis."""
    rtsp_url: str = Field(..., description="RTSP URL of the camera")


class AnalyzeFrameResponse(BaseModel):
    """Response model for frame analysis."""
    suggested_name: str
    text_found: Optional[str] = None
    scene_description: Optional[str] = None
    confidence: str = "medium"
    error: Optional[str] = None


class BatchAnalyzeRequest(BaseModel):
    """Request model for batch frame analysis."""
    cameras: List[dict] = Field(..., description="List of cameras with rtsp_url_main")


class BatchAnalyzeResponse(BaseModel):
    """Response model for batch frame analysis."""
    results: List[dict]
    total: int
    success: int
    failed: int


# Endpoints

@router.get("/brands", response_model=BrandsResponse)
async def list_brands(_=Depends(require_auth)):
    """List supported NVR brands."""
    brands = [
        {"id": "auto", "name": "Auto-Detect", "description": "Automatically detect NVR brand"},
        {"id": "hikvision", "name": "Hikvision", "description": "Hikvision NVR/DVR devices"},
        {"id": "dahua", "name": "Dahua", "description": "Dahua NVR/DVR devices"},
        {"id": "uniview", "name": "Uniview", "description": "Uniview NVR devices"},
        {"id": "axis", "name": "Axis", "description": "Axis network cameras and recorders"},
        {"id": "milesight", "name": "Milesight", "description": "Milesight NVR devices"},
        {"id": "bosch", "name": "Bosch", "description": "Bosch security devices"},
        {"id": "hanwha", "name": "Hanwha (Samsung Wisenet)", "description": "Hanwha/Samsung Wisenet devices"},
        {"id": "onvif", "name": "ONVIF (Generic)", "description": "Generic ONVIF-compatible devices"},
    ]
    return BrandsResponse(brands=brands)


@router.post("/discover", response_model=NVRDiscoverResponse)
async def discover_nvr(
    data: NVRDiscoverRequest,
    _=Depends(require_auth)
):
    """Discover cameras from an NVR."""
    try:
        result = await nvr_discovery.discover(
            host=data.host,
            username=data.username,
            password=data.password,
            port=data.port,
            rtsp_port=data.rtsp_port,
            brand=data.brand
        )

        cameras = [
            DiscoveredCameraResponse(
                channel_id=cam.channel_id,
                name=cam.name,
                rtsp_url_main=cam.rtsp_url_main,
                rtsp_url_sub=cam.rtsp_url_sub,
                resolution=cam.resolution,
                status=cam.status,
                model=cam.model
            )
            for cam in result.cameras
        ]

        return NVRDiscoverResponse(
            brand=result.brand,
            model=result.model,
            serial=result.serial,
            firmware=result.firmware,
            channels=result.channels,
            cameras=cameras,
            error=result.error
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/import", response_model=CameraImportResponse)
async def import_cameras(
    data: CameraImportRequest,
    _=Depends(require_auth)
):
    """Import discovered cameras as streams."""
    results = []
    imported = 0
    failed = 0

    for cam in data.cameras:
        channel_id = cam.get("channel_id", 0)
        name = cam.get("name", f"Camera {channel_id}")
        rtsp_url = cam.get("rtsp_url_sub" if data.use_sub_stream else "rtsp_url_main")

        if not rtsp_url:
            results.append(ImportResult(
                channel_id=channel_id,
                name=name,
                success=False,
                stream_id=None,
                error="No RTSP URL available"
            ))
            failed += 1
            continue

        # Check if URL already exists
        existing = await db.get_stream_by_url(rtsp_url)
        if existing:
            results.append(ImportResult(
                channel_id=channel_id,
                name=name,
                success=False,
                stream_id=existing.id,
                error="Stream with this URL already exists"
            ))
            failed += 1
            continue

        try:
            # Create stream
            stream = Stream(
                name=name,
                rtsp_url=rtsp_url,
                mode=data.mode,
                latency_mode=data.latency_mode,
                keep_alive_seconds=60
            )
            stream = await db.add_stream(stream)

            results.append(ImportResult(
                channel_id=channel_id,
                name=name,
                success=True,
                stream_id=stream.id,
                error=None
            ))
            imported += 1
        except Exception as e:
            results.append(ImportResult(
                channel_id=channel_id,
                name=name,
                success=False,
                stream_id=None,
                error=str(e)
            ))
            failed += 1

    return CameraImportResponse(
        total=len(data.cameras),
        imported=imported,
        failed=failed,
        results=results
    )


@router.post("/analyze-frame", response_model=AnalyzeFrameResponse)
async def analyze_camera_frame(
    data: AnalyzeFrameRequest,
    _=Depends(require_auth)
):
    """
    Analyze a camera frame using Claude Vision API to suggest a name.

    Captures a single frame from the RTSP stream and uses AI to:
    1. Read any text overlay (camera names burned into video)
    2. Describe the scene to suggest an appropriate name
    """
    # Get Claude API key
    api_key = await db.get_setting("claude_api_key")
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="Claude API key not configured. Go to Settings to add your API key."
        )

    # Analyze the stream
    result = await vision_analyzer.analyze_rtsp_stream(data.rtsp_url, api_key)

    return AnalyzeFrameResponse(
        suggested_name=result.suggested_name,
        text_found=result.text_found,
        scene_description=result.scene_description,
        confidence=result.confidence,
        error=result.error
    )


@router.post("/analyze-batch", response_model=BatchAnalyzeResponse)
async def analyze_cameras_batch(
    data: BatchAnalyzeRequest,
    _=Depends(require_auth)
):
    """
    Analyze multiple cameras in batch to suggest names.

    Processes cameras concurrently (max 3 at a time) to speed up analysis.
    """
    # Get Claude API key
    api_key = await db.get_setting("claude_api_key")
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="Claude API key not configured. Go to Settings to add your API key."
        )

    results = []
    success = 0
    failed = 0

    # Process in batches of 3 to avoid overwhelming the API
    semaphore = asyncio.Semaphore(3)

    async def analyze_one(camera: dict) -> dict:
        nonlocal success, failed
        async with semaphore:
            channel_id = camera.get("channel_id", 0)
            rtsp_url = camera.get("rtsp_url_main") or camera.get("rtsp_url")

            if not rtsp_url:
                failed += 1
                return {
                    "channel_id": channel_id,
                    "original_name": camera.get("name", ""),
                    "suggested_name": camera.get("name", f"Camera {channel_id}"),
                    "error": "No RTSP URL"
                }

            try:
                result = await vision_analyzer.analyze_rtsp_stream(rtsp_url, api_key)
                if result.error:
                    failed += 1
                else:
                    success += 1

                return {
                    "channel_id": channel_id,
                    "original_name": camera.get("name", ""),
                    "suggested_name": result.suggested_name,
                    "text_found": result.text_found,
                    "scene_description": result.scene_description,
                    "confidence": result.confidence,
                    "error": result.error
                }
            except Exception as e:
                failed += 1
                return {
                    "channel_id": channel_id,
                    "original_name": camera.get("name", ""),
                    "suggested_name": camera.get("name", f"Camera {channel_id}"),
                    "error": str(e)
                }

    # Run all analyses concurrently
    tasks = [analyze_one(cam) for cam in data.cameras]
    results = await asyncio.gather(*tasks)

    return BatchAnalyzeResponse(
        results=list(results),
        total=len(data.cameras),
        success=success,
        failed=failed
    )
