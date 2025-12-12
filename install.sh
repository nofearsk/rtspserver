#!/bin/bash
#
# RTSP to HLS Server - Installation Script
# Similar to Shinobi NVR installation
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

echo -e "${BLUE}"
echo "╔════════════════════════════════════════════════════════════╗"
echo "║          RTSP to HLS Server - Installation                 ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo -e "${YELLOW}Warning: Running as root. Will create dedicated user.${NC}"
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
                git \
                nodejs \
                npm
            ;;
        centos|rhel|fedora)
            sudo dnf install -y \
                python3 \
                python3-pip \
                ffmpeg \
                curl \
                git \
                nodejs \
                npm
            ;;
        arch|manjaro)
            sudo pacman -Sy --noconfirm \
                python \
                python-pip \
                ffmpeg \
                curl \
                git \
                nodejs \
                npm
            ;;
        *)
            echo -e "${YELLOW}Unknown OS. Please install manually: python3, pip, ffmpeg, nodejs, npm${NC}"
            ;;
    esac
}

# Install Node.js if not present (for PM2)
install_nodejs() {
    if ! command -v node &> /dev/null; then
        echo -e "${BLUE}Installing Node.js...${NC}"
        curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
        sudo apt-get install -y nodejs
    else
        echo -e "${GREEN}Node.js already installed: $(node --version)${NC}"
    fi
}

# Install PM2
install_pm2() {
    echo -e "${BLUE}Installing PM2...${NC}"

    if ! command -v pm2 &> /dev/null; then
        sudo npm install -g pm2
    else
        echo -e "${GREEN}PM2 already installed: $(pm2 --version)${NC}"
    fi
}

# Setup Python virtual environment
setup_python() {
    echo -e "${BLUE}Setting up Python virtual environment...${NC}"

    cd "$INSTALL_DIR"

    # Create virtual environment if not exists
    if [ ! -d "venv" ]; then
        python3 -m venv venv
    fi

    # Activate and install dependencies
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt

    echo -e "${GREEN}Python environment ready${NC}"
}

# Create data directories
create_directories() {
    echo -e "${BLUE}Creating data directories...${NC}"

    mkdir -p "$INSTALL_DIR/data"
    mkdir -p "$INSTALL_DIR/data/streams"
    mkdir -p "$INSTALL_DIR/logs"

    # Set permissions
    if [ "$RUN_AS_ROOT" = true ]; then
        chown -R $SUDO_USER:$SUDO_USER "$INSTALL_DIR"
    fi

    echo -e "${GREEN}Directories created${NC}"
}

# Create PM2 ecosystem file
create_pm2_config() {
    echo -e "${BLUE}Creating PM2 configuration...${NC}"

    cat > "$INSTALL_DIR/ecosystem.config.js" << 'EOF'
module.exports = {
  apps: [{
    name: 'rtspserver',
    cwd: __dirname,
    script: 'venv/bin/python',
    args: 'main.py',
    interpreter: 'none',
    instances: 1,
    autorestart: true,
    watch: false,
    max_memory_restart: '1G',
    env: {
      NODE_ENV: 'production',
      PYTHONUNBUFFERED: '1'
    },
    error_file: 'logs/error.log',
    out_file: 'logs/output.log',
    log_file: 'logs/combined.log',
    time: true,
    merge_logs: true,
    // Restart strategy
    exp_backoff_restart_delay: 100,
    max_restarts: 10,
    min_uptime: '10s',
    // Graceful shutdown
    kill_timeout: 5000,
    listen_timeout: 3000
  }]
};
EOF

    echo -e "${GREEN}PM2 configuration created${NC}"
}

# Create systemd service (alternative to PM2)
create_systemd_service() {
    echo -e "${BLUE}Creating systemd service...${NC}"

    # Get the user who will run the service
    if [ "$RUN_AS_ROOT" = true ]; then
        SERVICE_USER=${SUDO_USER:-root}
    else
        SERVICE_USER=$(whoami)
    fi

    sudo tee /etc/systemd/system/rtspserver.service > /dev/null << EOF
[Unit]
Description=RTSP to HLS Streaming Server
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/main.py
Restart=always
RestartSec=10
StandardOutput=append:$INSTALL_DIR/logs/output.log
StandardError=append:$INSTALL_DIR/logs/error.log
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    echo -e "${GREEN}Systemd service created${NC}"
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

# Check if PM2 is available
use_pm2() {
    command -v pm2 &> /dev/null
}

case "$1" in
    start)
        echo -e "${GREEN}Starting RTSP Server...${NC}"
        if use_pm2; then
            pm2 start ecosystem.config.js
        else
            sudo systemctl start rtspserver
        fi
        ;;
    stop)
        echo -e "${YELLOW}Stopping RTSP Server...${NC}"
        if use_pm2; then
            pm2 stop rtspserver
        else
            sudo systemctl stop rtspserver
        fi
        ;;
    restart)
        echo -e "${BLUE}Restarting RTSP Server...${NC}"
        if use_pm2; then
            pm2 restart rtspserver
        else
            sudo systemctl restart rtspserver
        fi
        ;;
    status)
        if use_pm2; then
            pm2 status rtspserver
        else
            sudo systemctl status rtspserver
        fi
        ;;
    logs)
        if use_pm2; then
            pm2 logs rtspserver --lines 100
        else
            tail -f logs/output.log logs/error.log
        fi
        ;;
    monitor)
        if use_pm2; then
            pm2 monit
        else
            watch -n 1 "systemctl status rtspserver"
        fi
        ;;
    update)
        echo -e "${BLUE}Updating RTSP Server...${NC}"

        # Stop server
        if use_pm2; then
            pm2 stop rtspserver 2>/dev/null || true
        else
            sudo systemctl stop rtspserver 2>/dev/null || true
        fi

        # Update code (if git repo)
        if [ -d ".git" ]; then
            git pull
        fi

        # Update dependencies
        source venv/bin/activate
        pip install -r requirements.txt --upgrade

        # Restart
        if use_pm2; then
            pm2 start ecosystem.config.js
        else
            sudo systemctl start rtspserver
        fi

        echo -e "${GREEN}Update complete!${NC}"
        ;;
    enable)
        echo -e "${GREEN}Enabling autostart...${NC}"
        if use_pm2; then
            pm2 startup
            pm2 save
        else
            sudo systemctl enable rtspserver
        fi
        echo -e "${GREEN}RTSP Server will start on boot${NC}"
        ;;
    disable)
        echo -e "${YELLOW}Disabling autostart...${NC}"
        if use_pm2; then
            pm2 unstartup
        else
            sudo systemctl disable rtspserver
        fi
        ;;
    *)
        echo ""
        echo -e "${BLUE}RTSP to HLS Server - Management${NC}"
        echo ""
        echo "Usage: $0 {start|stop|restart|status|logs|monitor|update|enable|disable}"
        echo ""
        echo "Commands:"
        echo "  start    - Start the server"
        echo "  stop     - Stop the server"
        echo "  restart  - Restart the server"
        echo "  status   - Show server status"
        echo "  logs     - View live logs"
        echo "  monitor  - Real-time monitoring"
        echo "  update   - Update and restart"
        echo "  enable   - Enable autostart on boot"
        echo "  disable  - Disable autostart"
        echo ""
        exit 1
        ;;
esac
EOF

    chmod +x "$INSTALL_DIR/rtspserver.sh"
    echo -e "${GREEN}Management script created: ./rtspserver.sh${NC}"
}

# Setup PM2 autostart
setup_autostart() {
    echo -e "${BLUE}Setting up autostart...${NC}"

    # Start with PM2
    cd "$INSTALL_DIR"
    pm2 start ecosystem.config.js

    # Generate startup script
    pm2 startup

    # Save current process list
    pm2 save

    echo -e "${GREEN}Autostart configured${NC}"
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

# Streams directory
STREAMS_DIR=./data/streams

# Security (change in production!)
SECRET_KEY=$(openssl rand -hex 32)

# FFmpeg settings
FFMPEG_PATH=ffmpeg
FFPROBE_PATH=ffprobe
EOF

        echo -e "${GREEN}Configuration file created: .env${NC}"
    fi
}

# Print completion message
print_completion() {
    # Get local IP
    LOCAL_IP=$(hostname -I | awk '{print $1}')

    echo ""
    echo -e "${GREEN}"
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║            Installation Complete!                          ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo ""
    echo -e "${BLUE}Server Management:${NC}"
    echo "  ./rtspserver.sh start     - Start server"
    echo "  ./rtspserver.sh stop      - Stop server"
    echo "  ./rtspserver.sh restart   - Restart server"
    echo "  ./rtspserver.sh logs      - View logs"
    echo "  ./rtspserver.sh status    - Check status"
    echo "  ./rtspserver.sh enable    - Enable autostart"
    echo ""
    echo -e "${BLUE}Or use PM2 directly:${NC}"
    echo "  pm2 start ecosystem.config.js"
    echo "  pm2 logs rtspserver"
    echo "  pm2 monit"
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
    echo "  - Node.js and PM2"
    echo "  - Configure autostart"
    echo ""

    read -p "Continue with installation? (y/n) " -n 1 -r
    echo

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled."
        exit 1
    fi

    install_dependencies
    install_nodejs
    install_pm2
    setup_python
    create_directories
    create_env_file
    create_pm2_config
    create_systemd_service
    create_management_script

    echo ""
    read -p "Start server and enable autostart now? (y/n) " -n 1 -r
    echo

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        setup_autostart
    fi

    print_completion
}

# Run main
main "$@"
