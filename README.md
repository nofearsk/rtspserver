# RTSP to HLS Streaming Server

A lightweight, self-hosted server that converts RTSP camera streams to HLS format for easy browser playback. Built with Python/FastAPI and FFmpeg.

## Features

- **RTSP to HLS Conversion** - Convert any RTSP stream to browser-playable HLS format
- **Web Interface** - Modern, responsive dashboard for managing streams
- **NVR Discovery** - Auto-discover cameras from Hikvision, Dahua, Uniview, and other NVRs
- **AI Camera Naming** - Use Claude Vision API to automatically suggest camera names based on video content
- **Multiple Stream Modes**:
  - **Always On** - Stream runs continuously
  - **On Demand** - Stream starts when viewers connect, stops after idle timeout
  - **Smart** - Automatically switches between modes based on usage
- **Token-based Authentication** - Secure stream access with JWT tokens
- **Auto Reconnection** - Automatically reconnects to cameras on failure
- **Resource Management** - Automatic cleanup of old HLS segments

## Requirements

- Python 3.10+
- FFmpeg
- Linux with systemd (Ubuntu, Debian, CentOS, etc.)

## Quick Install (One Command)

```bash
bash <(curl -s https://raw.githubusercontent.com/nofearsk/rtspserver/main/installers/rtspserver-install.sh)
```

This will:
- Install Python 3, FFmpeg, and dependencies
- Create a systemd service (auto-starts on boot)
- Start the server immediately

### Install Options

```bash
# Specify installation directory
bash <(curl -s ...) --dir /opt/rtspserver

# Specify branch
bash <(curl -s ...) --branch develop

# Use Python virtual environment (optional)
bash <(curl -s ...) --venv

# Don't auto-start after install
bash <(curl -s ...) --no-start
```

## Manual Installation

### 1. Clone the repository

```bash
git clone https://github.com/nofearsk/rtspserver.git
cd rtspserver
```

### 2. Run the install script

```bash
chmod +x install.sh
./install.sh
```

This will:
- Install system dependencies (Python, FFmpeg)
- Install Python packages (globally by default)
- Create systemd service (auto-starts on boot)
- Start the server

Options:
```bash
./install.sh --venv       # Use virtual environment
./install.sh --no-start   # Don't auto-start
```

### 3. Or install manually

```bash
# Install system dependencies
sudo apt update
sudo apt install python3 python3-pip ffmpeg

# Install Python dependencies
sudo pip3 install -r requirements.txt

# Run the server
python3 main.py
```

## Configuration

Create a `.env` file in the project root:

```env
# Server
HOST=0.0.0.0
PORT=8000
DEBUG=false

# Security (change these!)
SECRET_KEY=your-random-secret-key-here
API_KEY=your-api-key-here

# Paths
DATABASE_PATH=./rtspserver.db
STREAMS_DIR=/tmp/rtspserver/streams

# HLS Settings
HLS_TIME=2
HLS_LIST_SIZE=5

# Stream Defaults
DEFAULT_MODE=on_demand
KEEP_ALIVE_SECONDS=60
STARTUP_TIMEOUT=15

# Resource Limits
MAX_STREAMS=900                # Max cameras in database
MAX_CONCURRENT_STREAMS=30      # Max streams playing at once (FIFO)
```

All settings can be overridden with environment variables prefixed with `RTSP_`.

## Usage

### Server Management

```bash
rtspserver start     # Start server
rtspserver stop      # Stop server
rtspserver restart   # Restart server
rtspserver status    # Check status
rtspserver logs      # View logs
```

Or use systemctl directly:
```bash
sudo systemctl start rtspserver
sudo systemctl stop rtspserver
sudo systemctl status rtspserver
sudo journalctl -u rtspserver -f   # View live logs
```

### Running Manually (for development)

```bash
cd /opt/rtspserver
python3 main.py
```

### Access the Web Interface

Open your browser to:
- http://localhost:8000
- http://YOUR_SERVER_IP:8000

### First Time Setup

1. Open the web interface
2. Create your admin account
3. Add RTSP cameras manually or use NVR Discovery

## Adding Cameras

### Manual

1. Go to the Streams tab
2. Click "Add Stream"
3. Enter the RTSP URL: `rtsp://username:password@camera-ip:554/stream`
4. Configure stream mode and options
5. Save

### NVR Discovery

1. Go to "NVR Discovery" tab
2. Enter your NVR IP address and credentials
3. Select brand or use Auto-Detect
4. Click "Discover Cameras"
5. Select cameras to import

### AI Auto-Naming

Requires Claude API key (set in Settings):

1. Select one or more cameras
2. Click "Auto-Name (AI)"
3. The system captures a frame from each camera and uses Claude Vision to suggest descriptive names

## API Reference

### Authentication

```bash
# Login
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your-password"}'

# Response includes JWT token
{"access_token": "eyJ...", "token_type": "bearer"}
```

### Streams

```bash
# List all streams
curl http://localhost:8000/api/streams \
  -H "Authorization: Bearer YOUR_TOKEN"

# Add stream
curl -X POST http://localhost:8000/api/streams \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Front Door",
    "rtsp_url": "rtsp://user:pass@192.168.1.100:554/stream",
    "mode": "on_demand"
  }'

# Get HLS playlist token
curl http://localhost:8000/api/streams/1/token \
  -H "Authorization: Bearer YOUR_TOKEN"
# Returns: {"token": "...", "playlist_url": "/hls/1/stream.m3u8?token=..."}
```

### HLS Playback

```bash
# Get HLS playlist (requires token)
curl "http://localhost:8000/hls/1/stream.m3u8?token=YOUR_STREAM_TOKEN"
```

## Project Structure

```
rtspserver/
├── main.py              # FastAPI application entry point
├── config.py            # Configuration settings
├── database.py          # SQLite database models
├── api/                 # API endpoints
│   ├── auth.py          # Authentication
│   ├── streams.py       # Stream management
│   ├── nvr.py           # NVR discovery
│   ├── settings.py      # Settings management
│   └── webrtc.py        # WebRTC support
├── core/                # Core functionality
│   ├── stream_manager.py    # FFmpeg process management
│   ├── ffmpeg_builder.py    # FFmpeg command builder
│   ├── nvr_discovery.py     # NVR camera discovery
│   ├── vision_analyzer.py   # Claude Vision integration
│   └── stream_analyzer.py   # Stream analysis
├── static/              # Web interface
│   └── index.html       # Single-page application
├── install.sh           # Installation script
├── uninstall.sh         # Uninstallation script
└── installers/          # Remote installers
    └── rtspserver-install.sh
```

## Uninstalling

```bash
./uninstall.sh
```

This will:
- Stop PM2 process
- Remove systemd service
- Optionally delete database and stream data

To completely remove:
```bash
rm -rf /opt/rtspserver  # or your install directory
```

## Troubleshooting

### Stream not starting

1. Check the RTSP URL is correct and accessible
2. Verify camera credentials
3. Check FFmpeg is installed: `ffmpeg -version`
4. View logs: `./rtspserver.sh logs`

### High CPU usage

- Enable hardware acceleration in stream settings
- Reduce stream resolution/framerate
- Use "copy" mode instead of transcoding when possible

### Connection timeout

- Increase `STARTUP_TIMEOUT` in config
- Check network connectivity to camera
- Verify firewall allows RTSP traffic (port 554)

## License

MIT License

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
