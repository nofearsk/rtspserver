# RTSP Server API Documentation

**Base URL:** `http://localhost:8000`

## Table of Contents

- [Authentication](#authentication)
- [Auth Endpoints](#auth-endpoints)
- [Stream Endpoints](#stream-endpoints)
- [HLS Playback](#hls-playback)
- [NVR Discovery](#nvr-discovery)
- [Settings](#settings)
- [System Stats](#system-stats)

---

## Authentication

All API endpoints (except HLS playback) require authentication via one of:

### Session Cookie (Web UI)
After login, a `session_token` cookie is set automatically.

### API Key Header (External Access)
```
X-API-Key: your-api-key
```

### Stream Token (HLS Playback)
```
?token=jwt-token
```

---

## Auth Endpoints

**Prefix:** `/api/auth`

### Check Auth Status

```http
GET /api/auth/status
```

**Response:**
```json
{
  "setup_complete": true,
  "authenticated": true,
  "user": {
    "id": 1,
    "username": "admin",
    "is_admin": true
  }
}
```

### Initial Setup

```http
POST /api/auth/setup
Content-Type: application/json

{
  "username": "admin",
  "password": "your-secure-password"
}
```

> **Note:** Can only be called once. Creates the admin user.

### Login

```http
POST /api/auth/login
Content-Type: application/json

{
  "username": "admin",
  "password": "your-password"
}
```

**Response:**
```json
{
  "status": "ok",
  "user": {
    "id": 1,
    "username": "admin",
    "is_admin": true
  }
}
```

### Logout

```http
POST /api/auth/logout
```

### Change Password

```http
POST /api/auth/change-password
Content-Type: application/json

{
  "current_password": "old-password",
  "new_password": "new-secure-password"
}
```

### Get Current User

```http
GET /api/auth/me
```

### List API Keys (Admin)

```http
GET /api/auth/api-keys
```

**Response:**
```json
[
  {
    "id": 1,
    "name": "External App",
    "key_prefix": "rtsp_abc1",
    "created_at": "2024-01-15T10:30:00",
    "last_used": "2024-01-15T12:00:00"
  }
]
```

### Create API Key (Admin)

```http
POST /api/auth/api-keys
Content-Type: application/json

{
  "name": "My App"
}
```

**Response:**
```json
{
  "id": 1,
  "name": "My App",
  "key": "rtsp_abc123xyz789...",
  "key_prefix": "rtsp_abc1",
  "created_at": "2024-01-15T10:30:00"
}
```

> **Important:** The full `key` is only shown once at creation. Store it securely!

### Delete API Key (Admin)

```http
DELETE /api/auth/api-keys/{key_id}
```

---

## Stream Endpoints

**Prefix:** `/api/streams`

### List Streams

```http
GET /api/streams?page=1&per_page=20&status=running&group=Outdoor
```

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | int | 1 | Page number |
| `per_page` | int | 20 | Items per page (1-100) |
| `search` | string | - | Search by name |
| `status` | string | - | Filter: `stopped`, `starting`, `running`, `error`, `reconnecting` |
| `mode` | string | - | Filter: `always_on`, `on_demand`, `smart` |
| `group` | string | - | Filter by group name |
| `sort_by` | string | id | Sort field: `id`, `name`, `status`, `mode`, `created_at`, `viewer_count` |
| `sort_order` | string | asc | Sort order: `asc`, `desc` |

**Response:**
```json
{
  "streams": [
    {
      "id": "abc123",
      "name": "Front Door",
      "rtsp_url": "rtsp://user:pass@192.168.1.100:554/stream1",
      "mode": "on_demand",
      "status": "running",
      "video_codec": "h264",
      "audio_codec": "aac",
      "resolution": "1920x1080",
      "framerate": 25.0,
      "bitrate": 4000000,
      "viewer_count": 2,
      "last_error": null,
      "keep_alive_seconds": 60,
      "use_transcode": false,
      "latency_mode": "stable",
      "group_name": "Outdoor",
      "thumbnail": "data:image/jpeg;base64,...",
      "hls_url": "http://localhost:8000/hls/abc123/stream.m3u8",
      "is_running": true
    }
  ],
  "total": 50,
  "page": 1,
  "per_page": 20,
  "total_pages": 3,
  "counts": {
    "total": 50,
    "running": 10,
    "stopped": 35,
    "error": 5
  }
}
```

### Create Stream

```http
POST /api/streams
Content-Type: application/json

{
  "name": "Front Door Camera",
  "rtsp_url": "rtsp://user:pass@192.168.1.100:554/stream1",
  "mode": "on_demand",
  "keep_alive_seconds": 60,
  "use_transcode": false,
  "latency_mode": "stable",
  "group_name": "Outdoor",
  "ffmpeg_overrides": {
    "rtsp_transport": "tcp",
    "preset": "ultrafast"
  }
}
```

**Stream Modes:**

| Mode | Description |
|------|-------------|
| `on_demand` | Starts when viewer connects, stops after `keep_alive_seconds` of inactivity |
| `always_on` | Always running, auto-restarts on failure |
| `smart` | Switches between modes based on viewer patterns |

**Latency Modes:**

| Mode | Description |
|------|-------------|
| `stable` | Balanced latency and stability (recommended) |
| `low` | Lower latency, may have more buffering issues |

### Get Stream

```http
GET /api/streams/{stream_id}
```

### Update Stream

```http
PUT /api/streams/{stream_id}
Content-Type: application/json

{
  "name": "New Name",
  "mode": "always_on",
  "group_name": "Indoor"
}
```

### Delete Stream

```http
DELETE /api/streams/{stream_id}
```

### Start Stream

```http
POST /api/streams/{stream_id}/start
```

**Response:**
```json
{
  "stream_id": "abc123",
  "running": true,
  "status": "running",
  "viewer_count": 0,
  "start_time": "2024-01-15T10:30:00",
  "pid": 12345,
  "reconnect_count": 0
}
```

### Stop Stream

```http
POST /api/streams/{stream_id}/stop
```

### Get Stream Status

```http
GET /api/streams/{stream_id}/status
```

### Analyze Stream

Analyzes RTSP stream properties using FFprobe.

```http
POST /api/streams/{stream_id}/analyze
```

**Response:**
```json
{
  "is_valid": true,
  "error": null,
  "video_codec": "h264",
  "video_codec_name": "H.264 / AVC",
  "resolution": "1920x1080",
  "framerate": 25.0,
  "video_bitrate": 4000000,
  "audio_codec": "aac",
  "audio_codec_name": "AAC",
  "sample_rate": 48000,
  "channels": 2,
  "can_copy_video": true,
  "can_copy_audio": true,
  "needs_transcode": false,
  "transcode_reason": null,
  "recommended_settings": {
    "use_transcode": false
  }
}
```

### Get Playback Token

```http
GET /api/streams/{stream_id}/token?expires_hours=24&bind_ip=false
```

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `expires_hours` | int | 24 | Token expiry (1-168 hours) |
| `bind_ip` | bool | false | Bind token to client IP |

**Response:**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "expires_hours": 24,
  "hls_url": "http://localhost:8000/hls/abc123/stream.m3u8?token=eyJhbGci...",
  "player_url": "http://localhost:8000/?stream=abc123&token=eyJhbGci..."
}
```

### Viewer Heartbeat

Keep on-demand stream alive while watching.

```http
POST /api/streams/{stream_id}/heartbeat
Authorization: Bearer {stream_token}
```

### Capture Snapshot

```http
POST /api/streams/{stream_id}/snapshot
```

**Response:**
```json
{
  "status": "ok",
  "thumbnail": "data:image/jpeg;base64,...",
  "stream_id": "abc123"
}
```

### Get Groups

```http
GET /api/streams/groups/list
```

**Response:**
```json
{
  "groups": ["Outdoor", "Indoor", "Parking"]
}
```

### Get FFmpeg Override Options

```http
GET /api/streams/overrides/options
```

**Response:**
```json
{
  "options": {
    "rtsp_transport": "tcp",
    "buffer_size": "1048576",
    "timeout": "5000000",
    "preset": "ultrafast",
    "tune": "zerolatency"
  },
  "description": {
    "rtsp_transport": "RTSP transport protocol: tcp (reliable) or udp (lower latency)",
    "buffer_size": "Input buffer size in bytes (default: 1MB)",
    "timeout": "Connection timeout in microseconds",
    "preset": "x264 preset: ultrafast, superfast, veryfast, faster, fast, medium",
    "tune": "x264 tune: zerolatency (live), film, animation, grain"
  }
}
```

---

## Batch Operations

### Batch Start

```http
POST /api/streams/batch/start
Content-Type: application/json

{
  "stream_ids": ["abc123", "def456", "ghi789"]
}
```

**Response:**
```json
{
  "success": ["abc123", "def456"],
  "failed": [
    {"id": "ghi789", "error": "Stream not found"}
  ],
  "message": "Started 2 streams, 1 failed"
}
```

### Batch Stop

```http
POST /api/streams/batch/stop
Content-Type: application/json

{
  "stream_ids": ["abc123", "def456"]
}
```

### Batch Restart

```http
POST /api/streams/batch/restart
Content-Type: application/json

{
  "stream_ids": ["abc123", "def456"]
}
```

### Batch Delete

```http
DELETE /api/streams/batch
Content-Type: application/json

{
  "stream_ids": ["abc123", "def456"]
}
```

### Refresh All Thumbnails

```http
POST /api/streams/batch/refresh-thumbnails
```

---

## HLS Playback

### Get Playlist

```http
GET /hls/{stream_id}/stream.m3u8?token={jwt_token}
```

### Get Segment

```http
GET /hls/{stream_id}/segment_001.ts?token={jwt_token}
```

### Example: Play with VLC

```bash
vlc "http://localhost:8000/hls/abc123/stream.m3u8?token=eyJhbGci..."
```

### Example: HTML Video Player

```html
<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
<video id="video" controls></video>
<script>
  const video = document.getElementById('video');
  const hls = new Hls();
  hls.loadSource('http://localhost:8000/hls/abc123/stream.m3u8?token=eyJhbGci...');
  hls.attachMedia(video);
</script>
```

---

## NVR Discovery

**Prefix:** `/api/nvr`

### List Supported Brands

```http
GET /api/nvr/brands
```

**Response:**
```json
{
  "brands": [
    {"id": "auto", "name": "Auto-Detect", "description": "Automatically detect NVR brand"},
    {"id": "hikvision", "name": "Hikvision", "description": "Hikvision NVR/DVR devices"},
    {"id": "dahua", "name": "Dahua", "description": "Dahua NVR/DVR devices"},
    {"id": "uniview", "name": "Uniview", "description": "Uniview NVR devices"},
    {"id": "axis", "name": "Axis", "description": "Axis network cameras"},
    {"id": "onvif", "name": "ONVIF (Generic)", "description": "Generic ONVIF-compatible devices"}
  ]
}
```

### Discover NVR Cameras

```http
POST /api/nvr/discover
Content-Type: application/json

{
  "host": "192.168.1.50",
  "username": "admin",
  "password": "password123",
  "port": 80,
  "rtsp_port": 554,
  "brand": "auto"
}
```

**Response:**
```json
{
  "brand": "hikvision",
  "model": "DS-7608NI-K2",
  "serial": "ABC123456",
  "firmware": "V4.30.085",
  "channels": 8,
  "cameras": [
    {
      "channel_id": 1,
      "name": "Camera 1",
      "rtsp_url_main": "rtsp://admin:pass@192.168.1.50:554/Streaming/Channels/101",
      "rtsp_url_sub": "rtsp://admin:pass@192.168.1.50:554/Streaming/Channels/102",
      "resolution": "1920x1080",
      "status": "online",
      "model": "DS-2CD2143G0-I"
    }
  ],
  "error": null
}
```

### Import Cameras

```http
POST /api/nvr/import
Content-Type: application/json

{
  "cameras": [
    {
      "channel_id": 1,
      "name": "Front Door",
      "rtsp_url_main": "rtsp://...",
      "rtsp_url_sub": "rtsp://..."
    }
  ],
  "mode": "on_demand",
  "latency_mode": "stable",
  "use_sub_stream": false,
  "group_name": "NVR 192.168.1.50"
}
```

**Response:**
```json
{
  "total": 8,
  "imported": 7,
  "failed": 1,
  "results": [
    {
      "channel_id": 1,
      "name": "Front Door",
      "success": true,
      "stream_id": "abc123",
      "error": null
    },
    {
      "channel_id": 2,
      "name": "Back Door",
      "success": false,
      "stream_id": null,
      "error": "Stream with this URL already exists"
    }
  ]
}
```

### AI Frame Analysis (Requires Claude API Key)

```http
POST /api/nvr/analyze-frame
Content-Type: application/json

{
  "rtsp_url": "rtsp://user:pass@192.168.1.100:554/stream1"
}
```

**Response:**
```json
{
  "suggested_name": "Parking Lot East",
  "text_found": "CAM-03 PARKING",
  "scene_description": "Outdoor parking area with vehicles",
  "confidence": "high",
  "error": null
}
```

### Batch AI Analysis

```http
POST /api/nvr/analyze-batch
Content-Type: application/json

{
  "cameras": [
    {"channel_id": 1, "name": "Camera 1", "rtsp_url_main": "rtsp://..."},
    {"channel_id": 2, "name": "Camera 2", "rtsp_url_main": "rtsp://..."}
  ]
}
```

---

## Settings

**Prefix:** `/api/settings`

### Get All Settings

```http
GET /api/settings
```

**Response:**
```json
{
  "claude_api_configured": true,
  "server": {
    "max_concurrent_streams": 30,
    "keep_alive_seconds": 60,
    "segment_max_age_minutes": 5,
    "hls_time": 2,
    "hls_list_size": 5
  }
}
```

### Get Server Settings

```http
GET /api/settings/server
```

### Update Server Settings

```http
PUT /api/settings/server
Content-Type: application/json

{
  "max_concurrent_streams": 50,
  "keep_alive_seconds": 120,
  "segment_max_age_minutes": 10,
  "hls_time": 2,
  "hls_list_size": 6
}
```

### Check Claude API Status

```http
GET /api/settings/claude-api
```

**Response:**
```json
{
  "configured": true,
  "key_preview": "sk-ant-a...xyz"
}
```

### Set Claude API Key

```http
POST /api/settings/claude-api
Content-Type: application/json

{
  "api_key": "sk-ant-api03-..."
}
```

### Remove Claude API Key

```http
DELETE /api/settings/claude-api
```

---

## System Stats

**Prefix:** `/api/system`

### Get System Statistics

```http
GET /api/system/stats
```

**Response:**
```json
{
  "cpu_percent": 25.5,
  "cpu_count": 8,
  "ram_used": 4096,
  "ram_total": 16384,
  "ram_percent": 25.0,
  "gpu": {
    "name": "NVIDIA GeForce RTX 3080",
    "memory_used": 2048,
    "memory_total": 10240,
    "memory_percent": 20.0,
    "gpu_utilization": 15.0,
    "temperature": 45.0
  }
}
```

> **Note:** GPU stats only available with NVIDIA GPUs and nvidia-smi installed.

---

## Error Responses

All endpoints return errors in this format:

```json
{
  "detail": "Error message here"
}
```

**Common HTTP Status Codes:**

| Code | Description |
|------|-------------|
| 200 | Success |
| 201 | Created |
| 204 | No Content (successful delete) |
| 400 | Bad Request |
| 401 | Unauthorized (missing/invalid auth) |
| 403 | Forbidden (insufficient permissions) |
| 404 | Not Found |
| 500 | Internal Server Error |

---

## Example: cURL Commands

### Login and Get Token

```bash
# Login
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "yourpassword"}' \
  -c cookies.txt

# Use session cookie
curl -X GET http://localhost:8000/api/streams \
  -b cookies.txt
```

### Using API Key

```bash
# Create stream
curl -X POST http://localhost:8000/api/streams \
  -H "X-API-Key: rtsp_your_api_key_here" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Camera",
    "rtsp_url": "rtsp://user:pass@192.168.1.100:554/stream"
  }'

# Start stream
curl -X POST http://localhost:8000/api/streams/abc123/start \
  -H "X-API-Key: rtsp_your_api_key_here"

# Get playback token
curl -X GET "http://localhost:8000/api/streams/abc123/token" \
  -H "X-API-Key: rtsp_your_api_key_here"
```

---

## WebSocket (Future)

WebSocket endpoint for real-time updates is planned for future releases.

---

## Rate Limits

Currently no rate limits are enforced. For production deployments, consider adding a reverse proxy (nginx) with rate limiting.
