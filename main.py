"""RTSP to HLS Streaming Server - Main Application."""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database import db
from core.stream_manager import stream_manager
from api.streams import router as streams_router
from api.webrtc import router as webrtc_router
from api.nvr import router as nvr_router
from api.system import router as system_router
from api.users import router as users_router
from api.settings import router as settings_router
from api.auth import verify_stream_token

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting RTSP to HLS Server...")
    await db.connect()
    await stream_manager.start()
    logger.info(f"Server ready at http://{settings.host}:{settings.port}")

    yield

    # Shutdown
    logger.info("Shutting down...")
    await stream_manager.stop()
    await db.close()
    logger.info("Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="RTSP to HLS Server",
    description="Convert RTSP streams to HLS with auto-configuration",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

# Add CORS middleware to allow cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(streams_router)
app.include_router(webrtc_router)
app.include_router(nvr_router)
app.include_router(system_router)
app.include_router(users_router)
app.include_router(settings_router)


# HLS file serving with authentication
@app.api_route("/hls/{stream_id}/{filename:path}", methods=["GET", "HEAD"])
async def serve_hls(stream_id: str, filename: str, request: Request):
    """Serve HLS files with token authentication.

    Supports both GET and HEAD methods for player compatibility (VLC, etc.).
    """
    # Token is required for playlist (.m3u8), optional for segments (.ts)
    # This is because HLS.js fetches segments without query params
    token = request.query_params.get("token")

    is_playlist = filename.endswith(".m3u8")
    is_segment = filename.endswith(".ts")

    if is_playlist:
        # Playlist requires authentication
        if not token:
            raise HTTPException(status_code=401, detail="Token required")
        try:
            verify_stream_token(token, stream_id)
        except HTTPException:
            raise
    elif is_segment:
        # Segments are allowed without token (security through playlist auth)
        # The segment filenames are random enough to prevent guessing
        pass
    else:
        raise HTTPException(status_code=400, detail="Invalid file type")

    # Check if stream exists
    stream = await db.get_stream(stream_id)
    if not stream:
        raise HTTPException(status_code=404, detail="Stream not found")

    # Build file path
    file_path = settings.streams_dir / str(stream_id) / filename

    if not file_path.exists():
        # Stream might be starting, trigger start for on-demand
        if filename == "stream.m3u8":
            from api.auth import generate_viewer_id
            viewer_id = generate_viewer_id()
            success = await stream_manager.start_stream(stream_id, viewer_id)
            if success:
                # Wait a bit for first segment
                import asyncio
                for _ in range(30):  # Wait up to 15 seconds
                    await asyncio.sleep(0.5)
                    if file_path.exists():
                        break

        if not file_path.exists():
            raise HTTPException(
                status_code=404,
                detail="Stream not ready. Please wait a moment and retry."
            )

    # Determine content type
    content_type = "application/vnd.apple.mpegurl"
    if filename.endswith(".ts"):
        content_type = "video/mp2t"

    return FileResponse(
        file_path,
        media_type=content_type,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Access-Control-Allow-Origin": "*",
        }
    )


# Static files and UI
@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main UI."""
    index_path = Path(__file__).parent / "static" / "index.html"
    return FileResponse(
        index_path,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


# Mount static files
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


# Health check
@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info",
    )
