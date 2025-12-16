#!/bin/bash
#
# RTSP to HLS Server - Installation Script
#
# Options:
#   --venv      Use Python virtual environment (optional)
#   --no-start  Don't start server after installation
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Installation directory
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="rtspserver"
USE_VENV="no"
AUTO_START="yes"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --venv)
            USE_VENV="yes"
            shift
            ;;
        --no-start)
            AUTO_START="no"
            shift
            ;;
        *)
            shift
            ;;
    esac
done

echo -e "${BLUE}"
echo "╔════════════════════════════════════════════════════════════╗"
echo "║          RTSP to HLS Server - Installation                 ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo -e "${YELLOW}Warning: Running as root.${NC}"
    RUN_AS_ROOT=true
else
    RUN_AS_ROOT=false
fi

# Detect OS
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
        VERSION=$VERSION_ID
    elif [ -f /etc/debian_version ]; then
        OS="debian"
    elif [ -f /etc/redhat-release ]; then
        OS="centos"
    else
        OS="unknown"
    fi
    echo -e "${GREEN}Detected OS: $OS${NC}"
}

# Install system dependencies
install_dependencies() {
    echo -e "${BLUE}Installing system dependencies...${NC}"

    case $OS in
        ubuntu|debian)
            sudo apt-get update
            sudo apt-get install -y \
                python3 \
                python3-pip \
                python3-venv \
                ffmpeg \
                curl \
                git
            ;;
        centos|rhel|fedora)
            sudo dnf install -y \
                python3 \
                python3-pip \
                ffmpeg \
                curl \
                git
            ;;
        arch|manjaro)
            sudo pacman -Sy --noconfirm \
                python \
                python-pip \
                ffmpeg \
                curl \
                git
            ;;
        *)
            echo -e "${YELLOW}Unknown OS. Please install manually: python3, pip, ffmpeg${NC}"
            ;;
    esac
}

# Setup Python - with or without venv
setup_python() {
    echo -e "${BLUE}Installing Python dependencies...${NC}"

    cd "$INSTALL_DIR"

    if [ "$USE_VENV" = "yes" ]; then
        echo -e "${BLUE}Creating virtual environment...${NC}"
        python3 -m venv venv
        source venv/bin/activate
        pip install --upgrade pip
        pip install -r requirements.txt
        PYTHON_PATH="$INSTALL_DIR/venv/bin/python"
    else
        # Install globally (may need sudo)
        pip3 install --upgrade pip 2>/dev/null || sudo pip3 install --upgrade pip
        pip3 install -r requirements.txt 2>/dev/null || sudo pip3 install -r requirements.txt
        PYTHON_PATH=$(which python3)
    fi

    echo -e "${GREEN}Python dependencies installed${NC}"
}

# Create data directories
create_directories() {
    echo -e "${BLUE}Creating data directories...${NC}"

    mkdir -p "$INSTALL_DIR/data"
    mkdir -p "$INSTALL_DIR/logs"

    # Set permissions
    if [ "$RUN_AS_ROOT" = true ] && [ -n "$SUDO_USER" ]; then
        chown -R $SUDO_USER:$SUDO_USER "$INSTALL_DIR"
    fi

    echo -e "${GREEN}Directories created${NC}"
}

# Create systemd service
create_systemd_service() {
    echo -e "${BLUE}Creating systemd service...${NC}"

    # Get the user who will run the service
    if [ "$RUN_AS_ROOT" = true ]; then
        SERVICE_USER=${SUDO_USER:-root}
    else
        SERVICE_USER=$(whoami)
    fi

    # Determine python path
    if [ "$USE_VENV" = "yes" ]; then
        EXEC_START="$INSTALL_DIR/venv/bin/python $INSTALL_DIR/main.py"
    else
        EXEC_START="$(which python3) $INSTALL_DIR/main.py"
    fi

    sudo tee /etc/systemd/system/rtspserver.service > /dev/null << EOF
[Unit]
Description=RTSP to HLS Streaming Server
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$EXEC_START
Restart=always
RestartSec=10
StandardOutput=append:$INSTALL_DIR/logs/output.log
StandardError=append:$INSTALL_DIR/logs/error.log
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable rtspserver
    echo -e "${GREEN}Systemd service created and enabled${NC}"
}

# Create management script
create_management_script() {
    echo -e "${BLUE}Creating management script...${NC}"

    cat > "$INSTALL_DIR/rtspserver.sh" << 'EOF'
#!/bin/bash
#
# RTSP Server Management Script
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

case "$1" in
    start)
        echo -e "${GREEN}Starting RTSP Server...${NC}"
        sudo systemctl start rtspserver
        ;;
    stop)
        echo -e "${YELLOW}Stopping RTSP Server...${NC}"
        sudo systemctl stop rtspserver
        ;;
    restart)
        echo -e "${BLUE}Restarting RTSP Server...${NC}"
        sudo systemctl restart rtspserver
        ;;
    status)
        sudo systemctl status rtspserver
        ;;
    logs)
        tail -f logs/output.log logs/error.log
        ;;
    enable)
        echo -e "${GREEN}Enabling autostart...${NC}"
        sudo systemctl enable rtspserver
        echo -e "${GREEN}RTSP Server will start on boot${NC}"
        ;;
    disable)
        echo -e "${YELLOW}Disabling autostart...${NC}"
        sudo systemctl disable rtspserver
        ;;
    update)
        echo -e "${BLUE}Updating RTSP Server...${NC}"
        sudo systemctl stop rtspserver 2>/dev/null || true
        if [ -d ".git" ]; then
            git pull
        fi
        if [ -d "venv" ]; then
            source venv/bin/activate
            pip install -r requirements.txt --upgrade
        else
            pip3 install -r requirements.txt --upgrade 2>/dev/null || sudo pip3 install -r requirements.txt --upgrade
        fi
        sudo systemctl start rtspserver
        echo -e "${GREEN}Update complete!${NC}"
        ;;
    *)
        echo ""
        echo -e "${BLUE}RTSP to HLS Server - Management${NC}"
        echo ""
        echo "Usage: $0 {start|stop|restart|status|logs|enable|disable|update}"
        echo ""
        echo "Commands:"
        echo "  start    - Start the server"
        echo "  stop     - Stop the server"
        echo "  restart  - Restart the server"
        echo "  status   - Show server status"
        echo "  logs     - View live logs"
        echo "  enable   - Enable autostart on boot"
        echo "  disable  - Disable autostart"
        echo "  update   - Update and restart"
        echo ""
        exit 1
        ;;
esac
EOF

    chmod +x "$INSTALL_DIR/rtspserver.sh"

    # Create symlink for easy access
    sudo ln -sf "$INSTALL_DIR/rtspserver.sh" /usr/local/bin/rtspserver 2>/dev/null || true

    echo -e "${GREEN}Management script created: ./rtspserver.sh${NC}"
}

# Create .env file if not exists
create_env_file() {
    if [ ! -f "$INSTALL_DIR/.env" ]; then
        echo -e "${BLUE}Creating configuration file...${NC}"

        cat > "$INSTALL_DIR/.env" << EOF
# RTSP Server Configuration
HOST=0.0.0.0
PORT=8000
DEBUG=false

# Database
DATABASE_PATH=./data/rtspserver.db

# Streams directory (use /tmp for auto-cleanup)
STREAMS_DIR=/tmp/rtspserver/streams

# Security (change in production!)
SECRET_KEY=$(openssl rand -hex 32)

# FFmpeg settings
FFMPEG_PATH=ffmpeg
FFPROBE_PATH=ffprobe
EOF

        echo -e "${GREEN}Configuration file created: .env${NC}"
    fi
}

# Start and enable service
start_service() {
    echo -e "${BLUE}Starting service...${NC}"
    sudo systemctl start rtspserver
    echo -e "${GREEN}Service started and enabled on boot${NC}"
}

# Print completion message
print_completion() {
    # Get local IP
    LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

    echo ""
    echo -e "${GREEN}"
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║            Installation Complete!                          ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo ""
    echo -e "${BLUE}Server Management:${NC}"
    echo "  rtspserver start     - Start server"
    echo "  rtspserver stop      - Stop server"
    echo "  rtspserver restart   - Restart server"
    echo "  rtspserver logs      - View logs"
    echo "  rtspserver status    - Check status"
    echo ""
    echo -e "${BLUE}Or use systemctl:${NC}"
    echo "  sudo systemctl status rtspserver"
    echo "  sudo journalctl -u rtspserver -f"
    echo ""
    echo -e "${BLUE}Access the web interface:${NC}"
    echo "  http://localhost:8000"
    echo "  http://$LOCAL_IP:8000"
    echo ""
    echo -e "${YELLOW}First time setup:${NC}"
    echo "  1. Open the web interface"
    echo "  2. Create your admin account"
    echo "  3. Add your RTSP cameras"
    echo ""
}

# Main installation
main() {
    detect_os

    echo ""
    echo -e "${YELLOW}This script will install:${NC}"
    echo "  - Python 3 and dependencies"
    echo "  - FFmpeg"
    echo "  - Create systemd service (auto-start on boot)"
    if [ "$USE_VENV" = "yes" ]; then
        echo "  - Python virtual environment"
    fi
    echo ""

    read -p "Continue with installation? (y/n) " -n 1 -r
    echo

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled."
        exit 1
    fi

    install_dependencies
    setup_python
    create_directories
    create_env_file
    create_systemd_service
    create_management_script

    if [ "$AUTO_START" = "yes" ]; then
        start_service
    fi

    print_completion
}

# Run main
main "$@"
