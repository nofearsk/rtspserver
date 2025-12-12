"""Stream analyzer using ffprobe to detect stream properties."""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class StreamInfo:
    """Analyzed stream information."""
    # Video
    video_codec: Optional[str] = None
    video_codec_name: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    framerate: Optional[float] = None
    video_bitrate: Optional[int] = None
    profile: Optional[str] = None
    level: Optional[int] = None
    pix_fmt: Optional[str] = None

    # Audio
    audio_codec: Optional[str] = None
    audio_codec_name: Optional[str] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    audio_bitrate: Optional[int] = None

    # Stream info
    is_valid: bool = False
    error: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None

    # Recommendations
    can_copy_video: bool = False
    can_copy_audio: bool = False
    needs_transcode: bool = False
    transcode_reason: Optional[str] = None

    @property
    def resolution(self) -> Optional[str]:
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "video_codec": self.video_codec,
            "video_codec_name": self.video_codec_name,
            "resolution": self.resolution,
            "width": self.width,
            "height": self.height,
            "framerate": self.framerate,
            "video_bitrate": self.video_bitrate,
            "profile": self.profile,
            "pix_fmt": self.pix_fmt,
            "audio_codec": self.audio_codec,
            "audio_codec_name": self.audio_codec_name,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "audio_bitrate": self.audio_bitrate,
            "is_valid": self.is_valid,
            "error": self.error,
            "can_copy_video": self.can_copy_video,
            "can_copy_audio": self.can_copy_audio,
            "needs_transcode": self.needs_transcode,
            "transcode_reason": self.transcode_reason,
        }


# HLS-compatible codecs
HLS_VIDEO_CODECS = {"h264", "hevc", "h265"}
HLS_AUDIO_CODECS = {"aac", "mp3", "ac3"}


class StreamAnalyzer:
    """Analyze RTSP streams using ffprobe."""

    def __init__(self):
        self.ffprobe_path = settings.ffprobe_path
        self.timeout = 15  # seconds

    async def analyze(self, rtsp_url: str) -> StreamInfo:
        """Analyze an RTSP stream and return its properties."""
        info = StreamInfo()

        try:
            # Build ffprobe command
            cmd = [
                self.ffprobe_path,
                "-v", "error",  # Show errors but not info
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                "-rtsp_transport", "tcp",
                "-rtsp_flags", "prefer_tcp",  # Force client mode
                "-stimeout", str(self.timeout * 1000000),  # Socket timeout (microseconds)
                "-analyzeduration", "5000000",  # 5 seconds max analysis
                "-probesize", "5000000",  # 5MB probe size
                rtsp_url
            ]

            logger.info(f"Analyzing stream: {rtsp_url}")
            logger.debug(f"ffprobe command: {' '.join(cmd)}")

            # Run ffprobe
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self.timeout + 5
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                info.error = "Connection timeout - camera may be offline or unreachable"
                return info

            if proc.returncode != 0:
                stderr_text = stderr.decode().strip() if stderr else ""
                stdout_text = stdout.decode().strip() if stdout else ""
                logger.error(f"ffprobe failed (code {proc.returncode}): stderr={stderr_text}, stdout={stdout_text}")

                if stderr_text:
                    info.error = self._parse_error(stderr_text, rtsp_url)
                elif stdout_text:
                    info.error = self._parse_error(stdout_text, rtsp_url)
                else:
                    info.error = f"ffprobe failed with exit code {proc.returncode}"
                return info

            # Parse JSON output
            stdout_text = stdout.decode().strip() if stdout else ""
            if not stdout_text:
                info.error = "No stream data received - camera may not be streaming"
                return info

            try:
                data = json.loads(stdout_text)
                info.raw_data = data
            except json.JSONDecodeError as e:
                logger.error(f"JSON parse error: {e}, stdout: {stdout_text[:500]}")
                info.error = f"Failed to parse stream info: {e}"
                return info

            # Check if we got any streams
            if not data.get("streams"):
                info.error = "No video/audio streams found in RTSP source"
                return info

            # Extract stream information
            self._extract_stream_info(info, data)

            # Analyze compatibility
            self._analyze_compatibility(info)

            info.is_valid = True
            logger.info(f"Stream analysis complete: {info.video_codec} {info.resolution}")

        except FileNotFoundError:
            info.error = f"ffprobe not found at '{self.ffprobe_path}'. Please install FFmpeg."
        except Exception as e:
            logger.exception(f"Error analyzing stream: {e}")
            info.error = f"Analysis failed: {str(e)}"

        return info

    def _extract_stream_info(self, info: StreamInfo, data: Dict[str, Any]):
        """Extract video and audio info from ffprobe data."""
        streams = data.get("streams", [])

        for stream in streams:
            codec_type = stream.get("codec_type")

            if codec_type == "video" and not info.video_codec:
                info.video_codec = stream.get("codec_name", "").lower()
                info.video_codec_name = stream.get("codec_long_name")
                info.width = stream.get("width")
                info.height = stream.get("height")
                info.profile = stream.get("profile")
                info.level = stream.get("level")
                info.pix_fmt = stream.get("pix_fmt")

                # Parse framerate
                fps_str = stream.get("avg_frame_rate") or stream.get("r_frame_rate")
                if fps_str:
                    info.framerate = self._parse_framerate(fps_str)

                # Parse bitrate
                bitrate = stream.get("bit_rate")
                if bitrate:
                    info.video_bitrate = int(bitrate)

            elif codec_type == "audio" and not info.audio_codec:
                info.audio_codec = stream.get("codec_name", "").lower()
                info.audio_codec_name = stream.get("codec_long_name")
                info.sample_rate = int(stream.get("sample_rate", 0)) or None
                info.channels = stream.get("channels")

                bitrate = stream.get("bit_rate")
                if bitrate:
                    info.audio_bitrate = int(bitrate)

    def _parse_framerate(self, fps_str: str) -> Optional[float]:
        """Parse framerate string like '30/1' or '29.97'."""
        try:
            if "/" in fps_str:
                num, den = fps_str.split("/")
                if int(den) == 0:
                    return None
                return round(int(num) / int(den), 2)
            return round(float(fps_str), 2)
        except (ValueError, ZeroDivisionError):
            return None

    def _analyze_compatibility(self, info: StreamInfo):
        """Analyze if stream needs transcoding for HLS."""
        reasons = []

        # Check video codec
        if info.video_codec:
            video_codec_normalized = info.video_codec.lower()
            # Handle h265/hevc naming
            if video_codec_normalized in ("hevc", "h265"):
                video_codec_normalized = "hevc"

            if video_codec_normalized in ("h264", "avc"):
                info.can_copy_video = True
            elif video_codec_normalized in ("hevc", "h265"):
                info.can_copy_video = True  # Modern HLS supports HEVC
            else:
                info.can_copy_video = False
                reasons.append(f"Video codec '{info.video_codec}' not HLS-compatible")
        else:
            reasons.append("No video stream detected")

        # Check audio codec
        if info.audio_codec:
            if info.audio_codec.lower() in HLS_AUDIO_CODECS:
                info.can_copy_audio = True
            else:
                info.can_copy_audio = False
                reasons.append(f"Audio codec '{info.audio_codec}' needs transcoding to AAC")
        else:
            # No audio is fine
            info.can_copy_audio = True

        # Determine if transcoding is needed
        info.needs_transcode = not info.can_copy_video
        if reasons:
            info.transcode_reason = "; ".join(reasons)

    def _parse_error(self, error_msg: str, url: str) -> str:
        """Convert ffprobe error to user-friendly message."""
        error_lower = error_msg.lower()

        if "unable to open rtsp for listening" in error_lower or "cannot assign requested address" in error_lower:
            return "RTSP connection failed - camera may only allow one connection at a time"
        elif "connection refused" in error_lower:
            return "Connection refused - camera may be offline or port blocked"
        elif "unauthorized" in error_lower or "401" in error_lower:
            return "Authentication failed - check username/password in RTSP URL"
        elif "forbidden" in error_lower or "403" in error_lower:
            return "Access forbidden - check camera permissions"
        elif "not found" in error_lower or "404" in error_lower:
            return "Stream not found - check RTSP path in URL"
        elif "timeout" in error_lower or "timed out" in error_lower:
            return "Connection timeout - camera may be offline or network issue"
        elif "no route to host" in error_lower:
            return "No route to host - check IP address and network connectivity"
        elif "name or service not known" in error_lower:
            return "DNS resolution failed - check hostname"
        elif "invalid data" in error_lower:
            return "Invalid stream data - camera may not support RTSP or URL is incorrect"

        # Return truncated original error
        if len(error_msg) > 200:
            return error_msg[:200] + "..."
        return error_msg


# Global analyzer instance
analyzer = StreamAnalyzer()
