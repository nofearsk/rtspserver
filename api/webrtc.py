"""WebRTC signaling API endpoints."""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Depends
from pydantic import BaseModel

from database import db
from core.webrtc_handler import webrtc_handler, WEBRTC_AVAILABLE
from api.auth import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webrtc", tags=["webrtc"])


class OfferRequest(BaseModel):
    """Request for WebRTC offer."""
    stream_id: str


class AnswerRequest(BaseModel):
    """WebRTC answer from client."""
    stream_id: str
    sdp: str
    type: str = "answer"


class ICECandidateRequest(BaseModel):
    """ICE candidate from client."""
    stream_id: str
    candidate: dict


class WebRTCStatusResponse(BaseModel):
    """WebRTC status response."""
    available: bool
    message: str


@router.get("/status", response_model=WebRTCStatusResponse)
async def webrtc_status():
    """Check if WebRTC is available."""
    if WEBRTC_AVAILABLE:
        return WebRTCStatusResponse(
            available=True,
            message="WebRTC is available"
        )
    else:
        return WebRTCStatusResponse(
            available=False,
            message="WebRTC dependencies not installed. Run: pip install aiortc av"
        )


@router.post("/offer")
async def create_offer(
    request: OfferRequest,
    _=Depends(require_auth)
):
    """
    Create a WebRTC offer for a stream.

    Returns SDP offer to send to the browser.
    """
    if not WEBRTC_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="WebRTC not available. Install with: pip install aiortc av"
        )

    # Get stream from database
    stream = await db.get_stream(request.stream_id)
    if not stream:
        raise HTTPException(status_code=404, detail="Stream not found")

    # Create offer
    offer = await webrtc_handler.create_offer(request.stream_id, stream.rtsp_url)
    if not offer:
        raise HTTPException(status_code=500, detail="Failed to create WebRTC offer")

    return offer


@router.post("/answer")
async def handle_answer(
    request: AnswerRequest,
    _=Depends(require_auth)
):
    """
    Handle WebRTC answer from client.

    The client sends their SDP answer after receiving our offer.
    """
    if not WEBRTC_AVAILABLE:
        raise HTTPException(status_code=503, detail="WebRTC not available")

    success = await webrtc_handler.handle_answer(
        request.stream_id,
        request.sdp,
        request.type
    )

    if not success:
        raise HTTPException(status_code=400, detail="Failed to process answer")

    return {"status": "ok"}


@router.post("/ice-candidate")
async def handle_ice_candidate(
    request: ICECandidateRequest,
    _=Depends(require_auth)
):
    """Handle ICE candidate from client."""
    if not WEBRTC_AVAILABLE:
        raise HTTPException(status_code=503, detail="WebRTC not available")

    success = await webrtc_handler.handle_ice_candidate(
        request.stream_id,
        request.candidate
    )

    if not success:
        raise HTTPException(status_code=400, detail="Failed to add ICE candidate")

    return {"status": "ok"}


@router.delete("/{stream_id}")
async def stop_webrtc_stream(
    stream_id: str,
    _=Depends(require_auth)
):
    """Stop WebRTC stream."""
    if not WEBRTC_AVAILABLE:
        raise HTTPException(status_code=503, detail="WebRTC not available")

    await webrtc_handler.stop_stream(stream_id)
    return {"status": "stopped"}


@router.get("/{stream_id}/stats")
async def get_webrtc_stats(
    stream_id: str,
    _=Depends(require_auth)
):
    """Get WebRTC stream statistics."""
    if not WEBRTC_AVAILABLE:
        raise HTTPException(status_code=503, detail="WebRTC not available")

    return webrtc_handler.get_stats(stream_id)


# WebSocket for real-time signaling (alternative to REST API)
@router.websocket("/ws/{stream_id}")
async def webrtc_signaling(websocket: WebSocket, stream_id: str):
    """
    WebSocket endpoint for WebRTC signaling.

    Protocol:
    - Client connects
    - Server sends offer: {"type": "offer", "sdp": "..."}
    - Client sends answer: {"type": "answer", "sdp": "..."}
    - Both exchange ICE candidates: {"type": "ice-candidate", "candidate": {...}}
    """
    if not WEBRTC_AVAILABLE:
        await websocket.close(code=1003, reason="WebRTC not available")
        return

    await websocket.accept()

    try:
        # Get stream info
        stream = await db.get_stream(stream_id)
        if not stream:
            await websocket.send_json({"type": "error", "message": "Stream not found"})
            await websocket.close()
            return

        # Create and send offer
        offer = await webrtc_handler.create_offer(stream_id, stream.rtsp_url)
        if offer:
            await websocket.send_json({"type": "offer", **offer})
        else:
            await websocket.send_json({"type": "error", "message": "Failed to create offer"})
            await websocket.close()
            return

        # Handle messages from client
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "answer":
                success = await webrtc_handler.handle_answer(
                    stream_id,
                    data.get("sdp"),
                    "answer"
                )
                await websocket.send_json({
                    "type": "answer-result",
                    "success": success
                })

            elif msg_type == "ice-candidate":
                candidate = data.get("candidate")
                if candidate:
                    success = await webrtc_handler.handle_ice_candidate(
                        stream_id,
                        candidate
                    )
                    # ICE candidates don't need acknowledgment

            elif msg_type == "close":
                break

    except WebSocketDisconnect:
        logger.info(f"WebRTC WebSocket disconnected for stream {stream_id}")
    except Exception as e:
        logger.exception(f"WebRTC WebSocket error: {e}")
    finally:
        await webrtc_handler.stop_stream(stream_id)
