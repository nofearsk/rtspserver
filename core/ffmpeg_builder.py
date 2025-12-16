"""FFmpeg command builder with auto-configuration."""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any

from config import settings
from database import Stream
from core.stream_analyzer import StreamInfo

logger = logging.getLogger(__name__)


@dataclass
class FFmpegCommand:
    """Represents an FFmpeg command with all its parts."""
    input_args: List[str] = field(default_factory=list)
    input_url: str = ""
    video_args: List[str] = field(default_factory=list)
    audio_args: List[str] = field(default_factory=list)
    output_args: List[str] = field(default_factory=list)
    output_path: str = ""

    def build(self) -> List[str]:
        """Build complete FFmpeg command."""
        cmd = [settings.ffmpeg_path]
        cmd.extend(self.input_args)
        cmd.extend(["-i", self.input_url])
        cmd.extend(self.video_args)
        cmd.extend(self.audio_args)
        cmd.extend(self.output_args)
        cmd.append(self.output_path)
        return cmd

    def to_string(self) -> str:
        """Get command as string for display."""
        return " ".join(self.build())


class FFmpegBuilder:
    """Build optimized FFmpeg commands based on stream analysis."""

    def __init__(self):
        self.hls_time = settings.hls_time
        self.hls_list_size = settings.hls_list_size

    def build_hls_command(
        self,
        stream: Stream,
        stream_info: Optional[StreamInfo] = None,
        output_dir: Path = None
    ) -> FFmpegCommand:
        """
        Build FFmpeg command for RTSP to HLS conversion.

        Args:
            stream: Stream database model
            stream_info: Optional analyzed stream info
            output_dir: Output directory for HLS files

        Returns:
            FFmpegCommand object
        """
        cmd = FFmpegCommand()
        cmd.input_url = stream.rtsp_url

        # Parse any user overrides
        overrides = {}
        if stream.ffmpeg_overrides:
            try:
                overrides = json.loads(stream.ffmpeg_overrides)
            except json.JSONDecodeError:
                logger.warning(f"Invalid ffmpeg_overrides JSON for stream {stream.id}")

        # Determine latency mode from stream
        latency_mode = getattr(stream, 'latency_mode', 'stable') or 'stable'
        low_latency = (latency_mode == 'low')

        # Input arguments
        cmd.input_args = self._build_input_args(overrides, low_latency)

        # Video arguments
        cmd.video_args = self._build_video_args(stream, stream_info, overrides)

        # Audio arguments
        cmd.audio_args = self._build_audio_args(stream, stream_info, overrides)

        # Output arguments (HLS specific)
        cmd.output_args = self._build_output_args(overrides, low_latency)

        # Output path
        if output_dir is None:
            output_dir = settings.streams_dir / str(stream.id)
        output_dir.mkdir(parents=True, exist_ok=True)
        cmd.output_path = str(output_dir / "stream.m3u8")

        logger.info(f"Built FFmpeg command: {cmd.to_string()}")
        return cmd

    def _build_input_args(self, overrides: Dict[str, Any], low_latency: bool = False) -> List[str]:
        """Build input arguments with reconnection support."""
        args = []

        # Low latency mode - minimize buffering (override can force it)
        low_latency = overrides.get("low_latency", low_latency)
        if low_latency:
            args.extend([
                "-fflags", "nobuffer+flush_packets",  # No input buffering
                "-flags", "low_delay",  # Low delay mode
                "-max_delay", "0",  # No delay
                "-avioflags", "direct",  # Direct I/O
            ])

        # Use TCP for RTSP (more reliable than UDP)
        rtsp_transport = overrides.get("rtsp_transport", "tcp")
        args.extend(["-rtsp_transport", rtsp_transport])

        # Force client mode (not listen/server mode)
        args.extend(["-rtsp_flags", "prefer_tcp"])

        # Note: -reconnect options not supported in FFmpeg 4.x (Ubuntu 22.04)
        # Reconnection is handled by the stream_manager instead

        # Buffer settings - smaller for low latency
        if low_latency:
            buffer_size = overrides.get("buffer_size", "512000")  # ~512KB for low latency
        else:
            buffer_size = overrides.get("buffer_size", "1024000")  # ~1MB
        args.extend(["-buffer_size", str(buffer_size)])

        # Timeout settings (use 'timeout' for newer FFmpeg, fallback from 'stimeout')
        timeout_val = overrides.get("timeout", overrides.get("stimeout", "5000000"))  # 5 seconds in microseconds
        args.extend(["-timeout", str(timeout_val)])

        # Overwrite output
        args.append("-y")

        # Additional input overrides
        if "input_args" in overrides:
            args.extend(overrides["input_args"])

        return args

    def _build_video_args(
        self,
        stream: Stream,
        stream_info: Optional[StreamInfo],
        overrides: Dict[str, Any]
    ) -> List[str]:
        """Build video encoding arguments."""
        args = []

        # Check if we should transcode
        force_transcode = stream.use_transcode or overrides.get("transcode_video", False)

        can_copy = True
        if stream_info:
            can_copy = stream_info.can_copy_video

        if force_transcode or not can_copy:
            # Transcoding mode - use libx264 with ultrafast preset
            args.extend(["-c:v", "libx264"])

            # Preset (ultrafast for low CPU)
            preset = overrides.get("preset", "ultrafast")
            args.extend(["-preset", preset])

            # Tune for low latency
            tune = overrides.get("tune", "zerolatency")
            args.extend(["-tune", tune])

            # Profile for compatibility
            profile = overrides.get("profile", "baseline")
            args.extend(["-profile:v", profile])

            # CRF for quality (lower = better, 23 is default)
            crf = overrides.get("crf", "23")
            args.extend(["-crf", str(crf)])

            # Force keyframes at regular intervals for reliable HLS segmentation
            # This ensures each segment starts with a keyframe
            latency_mode = getattr(stream, 'latency_mode', 'stable') or 'stable'
            keyframe_interval = 1 if latency_mode == 'low' else 3
            args.extend(["-force_key_frames", f"expr:gte(t,n_forced*{keyframe_interval})"])

            # Optional bitrate limit
            if "video_bitrate" in overrides:
                args.extend(["-b:v", overrides["video_bitrate"]])
                args.extend(["-maxrate", overrides["video_bitrate"]])
                args.extend(["-bufsize", overrides.get("bufsize", "2M")])

            # Optional resolution scaling
            if "scale" in overrides:
                args.extend(["-vf", f"scale={overrides['scale']}"])

            logger.info(f"Stream {stream.id}: Using video transcoding (preset={preset})")
        else:
            # Copy mode - no transcoding (ultra low CPU)
            args.extend(["-c:v", "copy"])
            logger.info(f"Stream {stream.id}: Using video copy mode (no transcoding)")

        # Additional video overrides
        if "video_args" in overrides:
            args.extend(overrides["video_args"])

        return args

    def _build_audio_args(
        self,
        stream: Stream,
        stream_info: Optional[StreamInfo],
        overrides: Dict[str, Any]
    ) -> List[str]:
        """Build audio encoding arguments."""
        args = []

        # Check if we have audio and can copy it
        can_copy_audio = True
        has_audio = True

        if stream_info:
            can_copy_audio = stream_info.can_copy_audio
            has_audio = stream_info.audio_codec is not None

        # Option to disable audio entirely
        if overrides.get("no_audio", False) or not has_audio:
            args.extend(["-an"])
            logger.info(f"Stream {stream.id}: Audio disabled")
            return args

        force_transcode = overrides.get("transcode_audio", False)

        if force_transcode or not can_copy_audio:
            # Transcode to AAC
            args.extend(["-c:a", "aac"])

            # Audio bitrate
            audio_bitrate = overrides.get("audio_bitrate", "128k")
            args.extend(["-b:a", audio_bitrate])

            # Audio channels (stereo by default)
            channels = overrides.get("audio_channels", "2")
            args.extend(["-ac", str(channels)])

            logger.info(f"Stream {stream.id}: Transcoding audio to AAC")
        else:
            # Copy audio
            args.extend(["-c:a", "copy"])
            logger.info(f"Stream {stream.id}: Using audio copy mode")

        # Additional audio overrides
        if "audio_args" in overrides:
            args.extend(overrides["audio_args"])

        return args

    def _build_output_args(self, overrides: Dict[str, Any], low_latency: bool = False) -> List[str]:
        """Build HLS output arguments."""
        args = []

        # Low latency mode setting (override can force it)
        low_latency = overrides.get("low_latency", low_latency)

        # HLS format
        args.extend(["-f", "hls"])

        # Segment duration and playlist settings based on latency mode
        if low_latency:
            # Low latency: 1 second segments, 4 in playlist (2-4s total latency)
            hls_time = overrides.get("hls_time", 1)
            hls_list_size = overrides.get("hls_list_size", 4)
            hls_flags = overrides.get("hls_flags", "delete_segments+append_list+omit_endlist+split_by_time")
        else:
            # Stable/Reliable mode: 3 second segments, 8 in playlist (10-24s buffer)
            # Longer segments = more reliable, fewer gaps, better keyframe alignment
            hls_time = overrides.get("hls_time", 3)
            hls_list_size = overrides.get("hls_list_size", 8)
            hls_flags = overrides.get("hls_flags", "delete_segments+append_list+omit_endlist")

        args.extend(["-hls_time", str(hls_time)])
        args.extend(["-hls_list_size", str(hls_list_size)])
        args.extend(["-hls_flags", hls_flags])

        # Note: -force_key_frames is added in _build_video_args when transcoding
        # For copy mode, we rely on source keyframes (GOP)

        # Segment filename pattern
        args.extend(["-hls_segment_filename", "%d/segment_%03d.ts"])

        # Start number
        args.extend(["-start_number", "0"])

        # Additional output overrides
        if "output_args" in overrides:
            args.extend(overrides["output_args"])

        return args

    def get_default_overrides(self) -> Dict[str, Any]:
        """Get default override options for documentation."""
        return {
            "rtsp_transport": "tcp",  # tcp or udp
            "buffer_size": "1024000",  # Input buffer size
            "timeout": "5000000",  # Connection timeout (microseconds)
            "transcode_video": False,  # Force video transcoding
            "transcode_audio": False,  # Force audio transcoding
            "no_audio": False,  # Disable audio
            "preset": "ultrafast",  # x264 preset
            "tune": "zerolatency",  # x264 tune
            "profile": "baseline",  # x264 profile
            "crf": "23",  # Quality (0-51, lower=better)
            "video_bitrate": None,  # e.g., "2M"
            "audio_bitrate": "128k",
            "audio_channels": "2",
            "scale": None,  # e.g., "1280:720"
            "hls_time": self.hls_time,
            "hls_list_size": self.hls_list_size,
            "hls_flags": "delete_segments+append_list+omit_endlist",
            "input_args": [],  # Additional input args
            "video_args": [],  # Additional video args
            "audio_args": [],  # Additional audio args
            "output_args": [],  # Additional output args
        }


# Global builder instance
ffmpeg_builder = FFmpegBuilder()
