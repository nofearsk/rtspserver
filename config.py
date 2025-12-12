"""Configuration settings for RTSP to HLS server."""

from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path
from typing import Optional


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # Paths
    base_dir: Path = Path(__file__).parent
    streams_dir: Path = Field(default_factory=lambda: Path(__file__).parent / "streams")
    database_path: Path = Field(default_factory=lambda: Path(__file__).parent / "rtspserver.db")

    # Security
    secret_key: str = "change-this-in-production-use-strong-random-key"
    api_key: str = "change-this-api-key"
    token_expiry_hours: int = 24

    # FFmpeg defaults
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"

    # HLS settings
    hls_time: int = 2  # Segment duration in seconds
    hls_list_size: int = 5  # Number of segments in playlist
    hls_delete_segments: bool = True  # Delete old segments

    # Stream defaults
    default_mode: str = "on_demand"  # "always_on", "on_demand", "smart"
    keep_alive_seconds: int = 60  # Keep stream running after last viewer
    startup_timeout: int = 15  # Max seconds to wait for stream start
    reconnect_delay: int = 5  # Seconds before reconnect attempt
    max_reconnect_attempts: int = 3

    # Smart mode settings
    smart_idle_minutes: int = 5  # Switch to on-demand after this idle time

    # Resource limits
    max_streams: int = 50
    segment_cleanup_interval: int = 30  # Seconds between cleanup runs

    class Config:
        env_prefix = "RTSP_"
        env_file = ".env"


settings = Settings()

# Ensure streams directory exists
settings.streams_dir.mkdir(parents=True, exist_ok=True)
