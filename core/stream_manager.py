"""Stream manager for controlling FFmpeg processes."""

import asyncio
import logging
import shutil
import signal
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Set
from dataclasses import dataclass, field

from config import settings
from database import db, Stream, StreamStatus, StreamMode
from core.stream_analyzer import analyzer, StreamInfo
from core.ffmpeg_builder import ffmpeg_builder

logger = logging.getLogger(__name__)


@dataclass
class StreamProcess:
    """Holds information about a running stream process."""
    stream_id: str
    process: Optional[asyncio.subprocess.Process] = None
    task: Optional[asyncio.Task] = None
    start_time: Optional[datetime] = None
    last_viewer_time: Optional[datetime] = None
    viewer_count: int = 0
    viewers: Set[str] = field(default_factory=set)  # Track viewer IDs
    stream_info: Optional[StreamInfo] = None
    keep_alive_task: Optional[asyncio.Task] = None
    reconnect_count: int = 0


class StreamManager:
    """Manages FFmpeg streaming processes."""

    def __init__(self):
        self._processes: Dict[str, StreamProcess] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        """Start the stream manager."""
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        # Start all always-on streams
        streams = await db.get_always_on_streams()
        for stream in streams:
            await self.start_stream(stream.id)

        logger.info("Stream manager started")

    async def stop(self):
        """Stop all streams and cleanup."""
        self._running = False

        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Stop all running streams
        stream_ids = list(self._processes.keys())
        for stream_id in stream_ids:
            await self.stop_stream(stream_id)

        logger.info("Stream manager stopped")

    async def start_stream(self, stream_id: str, viewer_id: str = None) -> bool:
        """
        Start a stream.

        Args:
            stream_id: ID of the stream to start
            viewer_id: Optional viewer ID for tracking

        Returns:
            True if stream started or already running
        """
        async with self._lock:
            # Check if already running
            if stream_id in self._processes:
                proc = self._processes[stream_id]
                if viewer_id:
                    proc.viewers.add(viewer_id)
                    proc.viewer_count = len(proc.viewers)
                    proc.last_viewer_time = datetime.utcnow()
                    await db.update_viewer_count(stream_id, proc.viewer_count)
                return True

            # Get stream from database
            stream = await db.get_stream(stream_id)
            if not stream:
                logger.error(f"Stream {stream_id} not found")
                return False

            # Update status to starting
            await db.update_stream_status(stream_id, StreamStatus.STARTING)

            # Create stream process holder
            proc = StreamProcess(stream_id=stream_id)
            if viewer_id:
                proc.viewers.add(viewer_id)
                proc.viewer_count = 1
            proc.last_viewer_time = datetime.utcnow()

            # Analyze stream if we don't have info
            if not stream.video_codec:
                logger.info(f"Analyzing stream {stream_id}...")
                proc.stream_info = await analyzer.analyze(stream.rtsp_url)

                if not proc.stream_info.is_valid:
                    error = proc.stream_info.error or "Failed to analyze stream"
                    await db.update_stream_status(stream_id, StreamStatus.ERROR, error=error)
                    logger.error(f"Stream {stream_id} analysis failed: {error}")
                    return False

                # Update stream with detected info
                stream.video_codec = proc.stream_info.video_codec
                stream.audio_codec = proc.stream_info.audio_codec
                stream.resolution = proc.stream_info.resolution
                stream.framerate = proc.stream_info.framerate
                stream.bitrate = proc.stream_info.video_bitrate
                await db.update_stream(stream)

            self._processes[stream_id] = proc

        # Start FFmpeg process (outside lock to avoid blocking)
        success = await self._start_ffmpeg(stream_id)

        if success:
            await db.update_viewer_count(stream_id, proc.viewer_count)

        return success

    async def _start_ffmpeg(self, stream_id: str) -> bool:
        """Start the FFmpeg process for a stream."""
        proc = self._processes.get(stream_id)
        if not proc:
            return False

        stream = await db.get_stream(stream_id)
        if not stream:
            return False

        # Build output directory
        output_dir = settings.streams_dir / str(stream_id)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Build FFmpeg command
        cmd = ffmpeg_builder.build_hls_command(stream, proc.stream_info, output_dir)

        # Fix segment filename to use output directory
        cmd_list = cmd.build()
        for i, arg in enumerate(cmd_list):
            if arg == "%d/segment_%03d.ts":
                cmd_list[i] = str(output_dir / "segment_%03d.ts")

        try:
            logger.info(f"Starting FFmpeg for stream {stream_id}")
            logger.debug(f"Command: {' '.join(cmd_list)}")

            process = await asyncio.create_subprocess_exec(
                *cmd_list,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            proc.process = process
            proc.start_time = datetime.utcnow()

            # Update database
            await db.update_stream_status(
                stream_id, StreamStatus.RUNNING, pid=process.pid
            )

            # Start monitoring task
            proc.task = asyncio.create_task(self._monitor_process(stream_id))

            # Start keep-alive checker for on-demand streams
            if stream.mode == StreamMode.ON_DEMAND.value:
                proc.keep_alive_task = asyncio.create_task(
                    self._keep_alive_checker(stream_id, stream.keep_alive_seconds)
                )

            logger.info(f"Stream {stream_id} started (PID: {process.pid})")
            return True

        except Exception as e:
            logger.exception(f"Failed to start FFmpeg for stream {stream_id}: {e}")
            await db.update_stream_status(
                stream_id, StreamStatus.ERROR, error=str(e)
            )
            async with self._lock:
                self._processes.pop(stream_id, None)
            return False

    async def _monitor_process(self, stream_id: str):
        """Monitor FFmpeg process and handle exit."""
        proc = self._processes.get(stream_id)
        if not proc or not proc.process:
            return

        try:
            # Wait for process to complete
            stdout, stderr = await proc.process.communicate()

            exit_code = proc.process.returncode
            logger.info(f"FFmpeg for stream {stream_id} exited with code {exit_code}")

            if exit_code != 0:
                error_output = stderr.decode()[-500:] if stderr else "Unknown error"
                logger.error(f"FFmpeg error for stream {stream_id}: {error_output}")

                # Check if we should reconnect
                stream = await db.get_stream(stream_id)
                if stream and proc.reconnect_count < settings.max_reconnect_attempts:
                    proc.reconnect_count += 1
                    await db.update_stream_status(
                        stream_id, StreamStatus.RECONNECTING,
                        error=f"Reconnecting (attempt {proc.reconnect_count})..."
                    )
                    logger.info(f"Reconnecting stream {stream_id} (attempt {proc.reconnect_count})")

                    await asyncio.sleep(settings.reconnect_delay)

                    # Restart FFmpeg
                    await self._start_ffmpeg(stream_id)
                    return
                else:
                    await db.update_stream_status(
                        stream_id, StreamStatus.ERROR,
                        error=self._parse_ffmpeg_error(error_output)
                    )
            else:
                await db.update_stream_status(stream_id, StreamStatus.STOPPED)

        except asyncio.CancelledError:
            logger.info(f"Monitor task cancelled for stream {stream_id}")
        except Exception as e:
            logger.exception(f"Error monitoring stream {stream_id}: {e}")
            await db.update_stream_status(stream_id, StreamStatus.ERROR, error=str(e))
        finally:
            async with self._lock:
                self._processes.pop(stream_id, None)

    async def _keep_alive_checker(self, stream_id: str, keep_alive_seconds: int):
        """Check if stream should be stopped due to no viewers."""
        while True:
            await asyncio.sleep(10)  # Check every 10 seconds

            proc = self._processes.get(stream_id)
            if not proc:
                break

            if proc.viewer_count == 0 and proc.last_viewer_time:
                elapsed = datetime.utcnow() - proc.last_viewer_time
                if elapsed.total_seconds() > keep_alive_seconds:
                    logger.info(
                        f"Stream {stream_id} has no viewers for {keep_alive_seconds}s, stopping"
                    )
                    await self.stop_stream(stream_id)
                    break

    async def stop_stream(self, stream_id: str) -> bool:
        """Stop a stream."""
        # Get process info and tasks to cancel while holding lock
        async with self._lock:
            proc = self._processes.get(stream_id)
            if not proc:
                return False

            # Remove from processes dict immediately to prevent re-entry
            self._processes.pop(stream_id, None)

            # Get references to tasks/process we need to clean up
            keep_alive_task = proc.keep_alive_task
            monitor_task = proc.task
            ffmpeg_process = proc.process

        # Cancel tasks OUTSIDE the lock to avoid deadlock
        # (keep_alive_checker calls stop_stream which needs the lock)
        if keep_alive_task:
            keep_alive_task.cancel()
            try:
                await keep_alive_task
            except asyncio.CancelledError:
                pass

        # Terminate FFmpeg process
        if ffmpeg_process and ffmpeg_process.returncode is None:
            try:
                ffmpeg_process.terminate()
                try:
                    await asyncio.wait_for(ffmpeg_process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    ffmpeg_process.kill()
                    await ffmpeg_process.wait()
            except ProcessLookupError:
                pass

        # Cancel monitor task
        if monitor_task:
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass

        await db.update_stream_status(stream_id, StreamStatus.STOPPED)
        logger.info(f"Stream {stream_id} stopped")
        return True

    async def viewer_heartbeat(self, stream_id: str, viewer_id: str) -> bool:
        """
        Register a viewer heartbeat.

        Args:
            stream_id: Stream ID
            viewer_id: Unique viewer identifier

        Returns:
            True if stream is running
        """
        proc = self._processes.get(stream_id)

        if not proc:
            # Stream not running, try to start it (on-demand)
            stream = await db.get_stream(stream_id)
            if stream and stream.mode in (StreamMode.ON_DEMAND.value, StreamMode.SMART.value):
                return await self.start_stream(stream_id, viewer_id)
            return False

        # Update viewer tracking
        proc.viewers.add(viewer_id)
        proc.viewer_count = len(proc.viewers)
        proc.last_viewer_time = datetime.utcnow()
        await db.update_viewer_count(stream_id, proc.viewer_count)
        return True

    async def viewer_disconnect(self, stream_id: str, viewer_id: str):
        """Register a viewer disconnect."""
        proc = self._processes.get(stream_id)
        if proc and viewer_id in proc.viewers:
            proc.viewers.discard(viewer_id)
            proc.viewer_count = len(proc.viewers)
            proc.last_viewer_time = datetime.utcnow()
            await db.update_viewer_count(stream_id, proc.viewer_count)

    def get_stream_status(self, stream_id: str) -> dict:
        """Get current stream status."""
        proc = self._processes.get(stream_id)
        if not proc:
            return {
                "running": False,
                "status": "stopped",
                "viewer_count": 0
            }

        return {
            "running": True,
            "status": "running",
            "viewer_count": proc.viewer_count,
            "start_time": proc.start_time.isoformat() if proc.start_time else None,
            "pid": proc.process.pid if proc.process else None,
            "reconnect_count": proc.reconnect_count
        }

    def is_running(self, stream_id: str) -> bool:
        """Check if a stream is currently running."""
        return stream_id in self._processes

    async def _cleanup_loop(self):
        """Periodically cleanup old HLS segments."""
        while self._running:
            try:
                await asyncio.sleep(settings.segment_cleanup_interval)
                await self._cleanup_segments()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Error in cleanup loop: {e}")

    async def _cleanup_segments(self):
        """Remove HLS segments for stopped streams."""
        active_ids = set(self._processes.keys())

        for stream_dir in settings.streams_dir.iterdir():
            if stream_dir.is_dir():
                stream_id = stream_dir.name
                if stream_id not in active_ids:
                    # Check if stream exists in DB
                    stream = await db.get_stream(stream_id)
                    if not stream:
                        # Stream deleted, remove directory
                        shutil.rmtree(stream_dir)
                        logger.info(f"Cleaned up orphaned stream directory: {stream_dir}")

    def _parse_ffmpeg_error(self, error_output: str) -> str:
        """Parse FFmpeg error output to user-friendly message."""
        error_lower = error_output.lower()

        if "connection refused" in error_lower:
            return "Connection refused - camera offline or port blocked"
        elif "401" in error_lower or "unauthorized" in error_lower:
            return "Authentication failed - check RTSP credentials"
        elif "404" in error_lower or "not found" in error_lower:
            return "Stream not found - check RTSP URL path"
        elif "timeout" in error_lower:
            return "Connection timeout - network issue or camera offline"
        elif "no route" in error_lower:
            return "No route to host - check network/IP address"
        elif "invalid data" in error_lower:
            return "Invalid stream data - incompatible format"
        elif "codec not currently supported" in error_lower:
            return "Codec not supported - try enabling transcoding"

        # Return last line of error
        lines = [l.strip() for l in error_output.strip().split("\n") if l.strip()]
        if lines:
            return lines[-1][:200]
        return "Unknown error occurred"


# Global stream manager instance
stream_manager = StreamManager()
