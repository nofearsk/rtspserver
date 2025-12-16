"""Thumbnail capture utility using FFmpeg."""

import asyncio
import base64
import logging
from pathlib import Path
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)


async def capture_thumbnail(rtsp_url: str, width: int = 320, height: int = 180, timeout: int = 10) -> Optional[str]:
    """
    Capture a thumbnail from an RTSP stream.

    Args:
        rtsp_url: RTSP URL to capture from
        width: Thumbnail width (default 320)
        height: Thumbnail height (default 180)
        timeout: Timeout in seconds

    Returns:
        Base64 encoded JPEG image or None on failure
    """
    try:
        # FFmpeg command to capture a single frame as JPEG
        cmd = [
            settings.ffmpeg_path,
            '-rtsp_transport', 'tcp',
            '-i', rtsp_url,
            '-vframes', '1',  # Capture only 1 frame
            '-vf', f'scale={width}:{height}',
            '-f', 'image2',
            '-c:v', 'mjpeg',
            '-q:v', '5',  # Quality (2-31, lower is better)
            '-y',  # Overwrite
            'pipe:1'  # Output to stdout
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )

            if process.returncode == 0 and stdout:
                # Encode as base64
                thumbnail = base64.b64encode(stdout).decode('utf-8')
                return f"data:image/jpeg;base64,{thumbnail}"
            else:
                logger.warning(f"Failed to capture thumbnail: {stderr.decode()[-200:]}")
                return None

        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            logger.warning(f"Thumbnail capture timeout for {rtsp_url}")
            return None

    except Exception as e:
        logger.exception(f"Error capturing thumbnail: {e}")
        return None


async def capture_thumbnail_from_hls(stream_id: str, width: int = 320, height: int = 180) -> Optional[str]:
    """
    Capture a thumbnail from an existing HLS stream.

    Args:
        stream_id: Stream ID
        width: Thumbnail width
        height: Thumbnail height

    Returns:
        Base64 encoded JPEG image or None on failure
    """
    try:
        # Find the latest segment file
        stream_dir = settings.streams_dir / str(stream_id)
        if not stream_dir.exists():
            return None

        # Get the most recent .ts file
        ts_files = sorted(stream_dir.glob("*.ts"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not ts_files:
            return None

        latest_segment = ts_files[0]

        # FFmpeg command to capture a frame from the segment
        cmd = [
            settings.ffmpeg_path,
            '-i', str(latest_segment),
            '-vframes', '1',
            '-vf', f'scale={width}:{height}',
            '-f', 'image2',
            '-c:v', 'mjpeg',
            '-q:v', '5',
            '-y',
            'pipe:1'
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=5
        )

        if process.returncode == 0 and stdout:
            thumbnail = base64.b64encode(stdout).decode('utf-8')
            return f"data:image/jpeg;base64,{thumbnail}"

        return None

    except Exception as e:
        logger.debug(f"Error capturing HLS thumbnail: {e}")
        return None
