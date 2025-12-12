"""WebRTC stream handler for ultra-low latency streaming."""

import asyncio
import logging
import subprocess
import fractions
from typing import Dict, Optional, Set
from dataclasses import dataclass, field

try:
    from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
    from aiortc.contrib.media import MediaPlayer, MediaRelay
    from av import VideoFrame
    WEBRTC_AVAILABLE = True
except ImportError:
    WEBRTC_AVAILABLE = False

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class WebRTCStream:
    """Represents an active WebRTC stream."""
    stream_id: int
    rtsp_url: str
    relay: Optional[object] = None  # MediaRelay
    player: Optional[object] = None  # MediaPlayer
    connections: Set[object] = field(default_factory=set)  # RTCPeerConnection set
    task: Optional[asyncio.Task] = None


class RTSPVideoTrack(VideoStreamTrack if WEBRTC_AVAILABLE else object):
    """
    A video track that reads from RTSP using FFmpeg.
    """
    kind = "video"

    def __init__(self, rtsp_url: str):
        if WEBRTC_AVAILABLE:
            super().__init__()
        self.rtsp_url = rtsp_url
        self._process: Optional[subprocess.Popen] = None
        self._frame_count = 0
        self._start_time = None

    async def recv(self):
        """Receive the next video frame."""
        if not WEBRTC_AVAILABLE:
            raise RuntimeError("WebRTC not available")

        # This is a simplified implementation
        # In production, you'd read actual frames from FFmpeg
        pts, time_base = await self.next_timestamp()

        # Create a placeholder frame (in real impl, read from FFmpeg pipe)
        frame = VideoFrame(width=640, height=480, format='rgb24')
        frame.pts = pts
        frame.time_base = time_base

        return frame

    def stop(self):
        """Stop the video track."""
        if self._process:
            self._process.terminate()
            self._process = None


class WebRTCHandler:
    """Handles WebRTC connections for RTSP streams."""

    def __init__(self):
        self._streams: Dict[int, WebRTCStream] = {}
        self._lock = asyncio.Lock()

        if not WEBRTC_AVAILABLE:
            logger.warning("WebRTC dependencies not installed. Install with: pip install aiortc av")

    @property
    def available(self) -> bool:
        return WEBRTC_AVAILABLE

    async def create_offer(self, stream_id: int, rtsp_url: str) -> Optional[dict]:
        """
        Create a WebRTC offer for a stream.

        Returns SDP offer to send to the client.
        """
        if not WEBRTC_AVAILABLE:
            return None

        async with self._lock:
            # Get or create stream
            if stream_id not in self._streams:
                self._streams[stream_id] = WebRTCStream(
                    stream_id=stream_id,
                    rtsp_url=rtsp_url
                )

            stream = self._streams[stream_id]

            # Create peer connection
            pc = RTCPeerConnection()
            stream.connections.add(pc)

            @pc.on("connectionstatechange")
            async def on_connectionstatechange():
                logger.info(f"WebRTC connection state: {pc.connectionState}")
                if pc.connectionState == "failed" or pc.connectionState == "closed":
                    await self._cleanup_connection(stream_id, pc)

            # Create media player for RTSP
            try:
                # Use MediaPlayer to read from RTSP
                options = {
                    "rtsp_transport": "tcp",
                    "rtsp_flags": "prefer_tcp",
                    "fflags": "nobuffer",
                    "flags": "low_delay",
                }
                player = MediaPlayer(
                    rtsp_url,
                    format="rtsp",
                    options=options
                )
                stream.player = player

                # Add video track
                if player.video:
                    pc.addTrack(player.video)

                # Add audio track if available
                if player.audio:
                    pc.addTrack(player.audio)

            except Exception as e:
                logger.error(f"Failed to create media player: {e}")
                await pc.close()
                stream.connections.discard(pc)
                return None

            # Create offer
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)

            return {
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type
            }

    async def handle_answer(self, stream_id: int, sdp: str, sdp_type: str) -> bool:
        """
        Handle WebRTC answer from client.

        Args:
            stream_id: Stream ID
            sdp: SDP answer from client
            sdp_type: SDP type (should be "answer")

        Returns:
            True if successful
        """
        if not WEBRTC_AVAILABLE:
            return False

        stream = self._streams.get(stream_id)
        if not stream or not stream.connections:
            return False

        # Get the most recent connection (last one created)
        pc = next(iter(stream.connections), None)
        if not pc:
            return False

        try:
            answer = RTCSessionDescription(sdp=sdp, type=sdp_type)
            await pc.setRemoteDescription(answer)
            return True
        except Exception as e:
            logger.error(f"Failed to set remote description: {e}")
            return False

    async def handle_ice_candidate(self, stream_id: int, candidate: dict) -> bool:
        """Handle ICE candidate from client."""
        if not WEBRTC_AVAILABLE:
            return False

        stream = self._streams.get(stream_id)
        if not stream or not stream.connections:
            return False

        pc = next(iter(stream.connections), None)
        if not pc:
            return False

        try:
            await pc.addIceCandidate(candidate)
            return True
        except Exception as e:
            logger.error(f"Failed to add ICE candidate: {e}")
            return False

    async def _cleanup_connection(self, stream_id: int, pc):
        """Clean up a closed connection."""
        async with self._lock:
            stream = self._streams.get(stream_id)
            if stream:
                stream.connections.discard(pc)

                # If no more connections, cleanup the stream
                if not stream.connections:
                    if stream.player:
                        stream.player.video.stop() if stream.player.video else None
                        stream.player.audio.stop() if stream.player.audio else None
                    del self._streams[stream_id]

    async def stop_stream(self, stream_id: int):
        """Stop all WebRTC connections for a stream."""
        async with self._lock:
            stream = self._streams.get(stream_id)
            if stream:
                for pc in list(stream.connections):
                    await pc.close()
                stream.connections.clear()

                if stream.player:
                    if stream.player.video:
                        stream.player.video.stop()
                    if stream.player.audio:
                        stream.player.audio.stop()

                del self._streams[stream_id]

    def get_stats(self, stream_id: int) -> dict:
        """Get WebRTC stream statistics."""
        stream = self._streams.get(stream_id)
        if not stream:
            return {"active": False, "connections": 0}

        return {
            "active": True,
            "connections": len(stream.connections),
        }


# Global WebRTC handler instance
webrtc_handler = WebRTCHandler()
