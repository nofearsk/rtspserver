"""Vision analyzer using Claude API for camera name suggestions."""

import asyncio
import base64
import logging
import tempfile
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

import aiohttp

from config import settings

logger = logging.getLogger(__name__)

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-sonnet-4-20250514"


@dataclass
class FrameAnalysis:
    """Result of frame analysis."""
    suggested_name: str
    text_found: Optional[str] = None
    scene_description: Optional[str] = None
    confidence: str = "medium"
    error: Optional[str] = None


class VisionAnalyzer:
    """Analyzes camera frames using Claude Vision API."""

    def __init__(self):
        self._api_key: Optional[str] = None

    def set_api_key(self, api_key: str):
        """Set the Claude API key."""
        self._api_key = api_key

    async def capture_frame(self, rtsp_url: str, timeout: int = 10) -> Optional[bytes]:
        """
        Capture a single frame from an RTSP stream using FFmpeg.

        Args:
            rtsp_url: RTSP URL of the camera
            timeout: Timeout in seconds

        Returns:
            JPEG image bytes or None on failure
        """
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            tmp_path = tmp.name

        try:
            # FFmpeg command to capture single frame
            cmd = [
                'ffmpeg',
                '-y',  # Overwrite output
                '-rtsp_transport', 'tcp',
                '-i', rtsp_url,
                '-frames:v', '1',  # Single frame
                '-q:v', '2',  # High quality JPEG
                '-f', 'image2',
                tmp_path
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                _, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.error(f"Frame capture timed out for {rtsp_url}")
                return None

            if process.returncode != 0:
                logger.error(f"FFmpeg failed: {stderr.decode()[-500:]}")
                return None

            # Read the captured frame
            tmp_file = Path(tmp_path)
            if tmp_file.exists() and tmp_file.stat().st_size > 0:
                return tmp_file.read_bytes()
            return None

        except Exception as e:
            logger.exception(f"Error capturing frame: {e}")
            return None
        finally:
            # Cleanup temp file
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

    async def analyze_frame(
        self,
        image_data: bytes,
        api_key: str = None
    ) -> FrameAnalysis:
        """
        Analyze a camera frame using Claude Vision API.

        Args:
            image_data: JPEG image bytes
            api_key: Optional API key (uses stored key if not provided)

        Returns:
            FrameAnalysis with suggested name and details
        """
        key = api_key or self._api_key
        if not key:
            return FrameAnalysis(
                suggested_name="Camera",
                error="Claude API key not configured"
            )

        # Encode image to base64
        image_b64 = base64.standard_b64encode(image_data).decode('utf-8')

        prompt = """Analyze this security camera image and suggest a short, descriptive name for this camera.

Instructions:
1. First, look for any text overlay on the image (camera names are often burned into the video by NVRs)
2. If you find text that looks like a camera name, use that
3. If no text is found, describe what the camera is viewing in 2-4 words

Respond in this exact JSON format:
{
    "suggested_name": "Short Name Here",
    "text_found": "any text overlay found or null",
    "scene_description": "brief description of what the camera shows",
    "confidence": "high/medium/low"
}

Examples of good names:
- "Front Entrance"
- "Parking Lot A"
- "Server Room"
- "Loading Dock 2"
- "Main Hallway"
- "CAM-01" (if that text was found in overlay)

Keep the name short (2-4 words max). Only respond with JSON, no other text."""

        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                }

                payload = {
                    "model": CLAUDE_MODEL,
                    "max_tokens": 256,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/jpeg",
                                        "data": image_b64
                                    }
                                },
                                {
                                    "type": "text",
                                    "text": prompt
                                }
                            ]
                        }
                    ]
                }

                async with session.post(
                    CLAUDE_API_URL,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Claude API error: {response.status} - {error_text}")
                        return FrameAnalysis(
                            suggested_name="Camera",
                            error=f"API error: {response.status}"
                        )

                    result = await response.json()

                    # Extract text content from response
                    content = result.get("content", [])
                    if content and content[0].get("type") == "text":
                        text = content[0].get("text", "")

                        # Parse JSON response
                        import json
                        try:
                            # Find JSON in response
                            json_start = text.find('{')
                            json_end = text.rfind('}') + 1
                            if json_start >= 0 and json_end > json_start:
                                data = json.loads(text[json_start:json_end])
                                return FrameAnalysis(
                                    suggested_name=data.get("suggested_name", "Camera"),
                                    text_found=data.get("text_found"),
                                    scene_description=data.get("scene_description"),
                                    confidence=data.get("confidence", "medium")
                                )
                        except json.JSONDecodeError:
                            # If JSON parsing fails, try to extract name from text
                            logger.warning(f"Failed to parse JSON from Claude response: {text}")
                            # Just use the first line as the name
                            name = text.strip().split('\n')[0][:50]
                            return FrameAnalysis(
                                suggested_name=name if name else "Camera",
                                scene_description=text[:200]
                            )

                    return FrameAnalysis(
                        suggested_name="Camera",
                        error="No content in API response"
                    )

        except asyncio.TimeoutError:
            return FrameAnalysis(
                suggested_name="Camera",
                error="API request timed out"
            )
        except Exception as e:
            logger.exception(f"Error calling Claude API: {e}")
            return FrameAnalysis(
                suggested_name="Camera",
                error=str(e)
            )

    async def analyze_rtsp_stream(
        self,
        rtsp_url: str,
        api_key: str = None
    ) -> FrameAnalysis:
        """
        Capture frame from RTSP and analyze it.

        Args:
            rtsp_url: RTSP URL of the camera
            api_key: Optional API key

        Returns:
            FrameAnalysis with suggested name
        """
        # Capture frame
        frame_data = await self.capture_frame(rtsp_url)
        if not frame_data:
            return FrameAnalysis(
                suggested_name="Camera",
                error="Failed to capture frame from camera"
            )

        # Analyze frame
        return await self.analyze_frame(frame_data, api_key)


# Global instance
vision_analyzer = VisionAnalyzer()
