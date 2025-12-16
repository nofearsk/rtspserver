#!/bin/bash
#
# RTSP to HLS Server - One-Line Installer
#
# Usage:
#   bash <(curl -s https://raw.githubusercontent.com/nofearsk/rtspserver/main/installers/rtspserver-install.sh)
#
# Options:
#   --branch develop    Use specific branch
#   --dir /opt/custom   Custom install directory
#   --venv              Use Python virtual environment
#   --no-start          Don't start server after install
#

set -e

# Default values
REPO_URL="https://github.com/nofearsk/rtspserver.git"
BRANCH="main"
INSTALL_DIR="/opt/rtspserver"
USE_VENV="no"
AUTO_START="yes"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Banner
show_banner() {
    echo -e "${CYAN}"
    cat << 'EOF'
    ____  __________________     _____
   / __ \/_  __/ ___/ __  /    / ___/___  ______   _____  _____
  / /_/ / / /  \__ \/ /_/ /    \__ \/ _ \/ ___/ | / / _ \/ ___/
 / _, _/ / /  ___/ / ____/    ___/ /  __/ /   | |/ /  __/ /
/_/ |_| /_/  /____/_/        /____/\___/_/    |___/\___/_/

    RTSP to HLS Streaming Server - Installer
EOF
    echo -e "${NC}"
}

# Parse arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --branch|-b)
                BRANCH="$2"
                shift 2
                ;;
            --dir|-d)
                INSTALL_DIR="$2"
                shift 2
                ;;
            --venv)
                USE_VENV="yes"
                shift
                ;;
            --no-start)
                AUTO_START="no"
                shift
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                echo -e "${RED}Unknown option: $1${NC}"
                exit 1
                ;;
        esac
    done
}

show_help() {
    echo "RTSP Server Installer"
    echo ""
    echo "Usage: bash <(curl -s URL) [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --branch, -b    Git branch to use (default: main)"
    echo "  --dir, -d       Installation directory (default: /opt/rtspserver)"
    echo "  --venv          Use Python virtual environment (optional)"
    echo "  --no-start      Don't start server after installation"
    echo "  --help, -h      Show this help"
}

# Check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        echo -e "${YELLOW}Note: Some operations may require sudo password.${NC}"
    fi
}

# Detect OS
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
        OS_VERSION=$VERSION_ID
    elif [ -f /etc/debian_version ]; then
        OS="debian"
    elif [ -f /etc/redhat-release ]; then
        OS="centos"
    else
        OS="unknown"
    fi
    echo -e "${GREEN}Detected OS: $OS $OS_VERSION${NC}"
}

# Install system dependencies
install_system_deps() {
    echo -e "${BLUE}[1/5] Installing system dependencies...${NC}"

    case $OS in
        ubuntu|debian)
            sudo apt-get update -qq
            sudo apt-get install -y -qq \
                python3 \
                python3-pip \
                python3-venv \
                ffmpeg \
                curl \
                git \
                > /dev/null
            ;;
        centos|rhel|rocky|almalinux)
            sudo dnf install -y -q \
                python3 \
                python3-pip \
                ffmpeg \
                curl \
                git
            ;;
        fedora)
            sudo dnf install -y -q \
                python3 \
                python3-pip \
                ffmpeg \
                curl \
                git
            ;;
        arch|manjaro)
            sudo pacman -Sy --noconfirm --quiet \
                python \
                python-pip \
                ffmpeg \
                curl \
                git
            ;;
        *)
            echo -e "${YELLOW}Unknown OS. Please install: python3, pip, ffmpeg, git${NC}"
            read -p "Continue anyway? (y/n) " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
            ;;
    esac
    echo -e "${GREEN}✓ System dependencies installed${NC}"
}

# Clone or download repository
download_source() {
    echo -e "${BLUE}[2/5] Downloading RTSP Server...${NC}"

    # Create parent directory
    sudo mkdir -p "$(dirname "$INSTALL_DIR")"

    # Clone repository
    if [ -d "$INSTALL_DIR" ]; then
        echo -e "${YELLOW}Directory exists. Updating...${NC}"
        cd "$INSTALL_DIR"
        sudo git fetch origin
        sudo git checkout "$BRANCH"
        sudo git pull origin "$BRANCH"
    else
        sudo git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR"
    fi

    # Set ownership
    if [ -n "$SUDO_USER" ]; then
        sudo chown -R "$SUDO_USER:$SUDO_USER" "$INSTALL_DIR"
    else
        sudo chown -R "$(whoami):$(whoami)" "$INSTALL_DIR"
    fi

    cd "$INSTALL_DIR"
    echo -e "${GREEN}✓ Source code downloaded to $INSTALL_DIR${NC}"
}

# Check if PEP 668 (externally-managed-environment) is in effect
check_pep668() {
    # Check if we need venv due to PEP 668 (Ubuntu 24.04+, Debian 12+, etc.)
    if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
        # Python 3.11+ - check for EXTERNALLY-MANAGED marker
        STDLIB_PATH=$(python3 -c "import sysconfig; print(sysconfig.get_path('stdlib'))" 2>/dev/null)
        if [ -f "$STDLIB_PATH/EXTERNALLY-MANAGED" ]; then
            return 0  # PEP 668 in effect
        fi
    fi
    return 1  # No PEP 668
}

# Setup Python
setup_python() {
    echo -e "${BLUE}[3/5] Installing Python dependencies...${NC}"

    cd "$INSTALL_DIR"

    # Auto-enable venv if PEP 668 is in effect (Ubuntu 24.04+, Debian 12+)
    if [ "$USE_VENV" != "yes" ] && check_pep668; then
        echo -e "${YELLOW}PEP 668 detected - using virtual environment automatically${NC}"
        USE_VENV="yes"
    fi

    if [ "$USE_VENV" = "yes" ]; then
        python3 -m venv venv
        source venv/bin/activate
        pip install --upgrade pip -q
        pip install -r requirements.txt -q
    else
        pip3 install --upgrade pip -q 2>/dev/null || sudo pip3 install --upgrade pip -q
        pip3 install -r requirements.txt -q 2>/dev/null || sudo pip3 install -r requirements.txt -q
    fi

    echo -e "${GREEN}✓ Python dependencies installed${NC}"
}

# Create configuration files
create_configs() {
    echo -e "${BLUE}[4/5] Creating configuration files...${NC}"

    cd "$INSTALL_DIR"

    # Create directories
    mkdir -p data logs

    # Create .env if not exists
    if [ ! -f .env ]; then
        cat > .env << EOF
HOST=0.0.0.0
PORT=8000
DEBUG=false
DATABASE_PATH=./data/rtspserver.db
STREAMS_DIR=/tmp/rtspserver/streams
SECRET_KEY=$(openssl rand -hex 32)
EOF
    fi

    # Create management script
    cat > rtspserver << 'MGMT'
#!/bin/bash
cd "$(dirname "$0")"

case "$1" in
    start)   sudo systemctl start rtspserver ;;
    stop)    sudo systemctl stop rtspserver ;;
    restart) sudo systemctl restart rtspserver ;;
    status)  sudo systemctl status rtspserver ;;
    logs)    tail -f logs/output.log logs/error.log ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac
MGMT
    chmod +x rtspserver

    # Create symlink for easy access
    sudo ln -sf "$INSTALL_DIR/rtspserver" /usr/local/bin/rtspserver 2>/dev/null || true

    echo -e "${GREEN}✓ Configuration files created${NC}"
}

# Create and start systemd service
setup_service() {
    echo -e "${BLUE}[5/5] Setting up systemd service...${NC}"

    cd "$INSTALL_DIR"

    # Get the user
    if [ -n "$SUDO_USER" ]; then
        SERVICE_USER="$SUDO_USER"
    else
        SERVICE_USER="$(whoami)"
    fi

    # Determine python path
    if [ "$USE_VENV" = "yes" ]; then
        EXEC_START="$INSTALL_DIR/venv/bin/python $INSTALL_DIR/main.py"
    else
        EXEC_START="$(which python3) $INSTALL_DIR/main.py"
    fi

    # Create systemd service
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

    if [ "$AUTO_START" = "yes" ]; then
        sudo systemctl start rtspserver
    fi

    echo -e "${GREEN}✓ Service created and enabled${NC}"
}

# Show completion message
show_complete() {
    LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗"
    echo -e "║          Installation Complete!                            ║"
    echo -e "╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${CYAN}Access the web interface:${NC}"
    echo "  → http://localhost:8000"
    echo "  → http://$LOCAL_IP:8000"
    echo ""
    echo -e "${CYAN}Server management:${NC}"
    echo "  rtspserver start    - Start server"
    echo "  rtspserver stop     - Stop server"
    echo "  rtspserver restart  - Restart server"
    echo "  rtspserver logs     - View logs"
    echo "  rtspserver status   - Check status"
    echo ""
    echo -e "${CYAN}Or use systemctl:${NC}"
    echo "  sudo systemctl status rtspserver"
    echo "  sudo journalctl -u rtspserver -f"
    echo ""
    echo -e "${YELLOW}First time setup:${NC}"
    echo "  1. Open the web interface in your browser"
    echo "  2. Create your admin account"
    echo "  3. Add RTSP cameras"
    echo ""
    echo -e "${GREEN}Installation directory: $INSTALL_DIR${NC}"
    echo ""
}

# Main
main() {
    show_banner
    parse_args "$@"
    check_root
    detect_os

    echo ""
    echo -e "${YELLOW}Installation settings:${NC}"
    echo "  Directory: $INSTALL_DIR"
    echo "  Branch: $BRANCH"
    echo "  Virtual env: $USE_VENV"
    echo "  Auto-start: $AUTO_START"
    echo ""

    read -p "Continue with installation? (y/n) " -n 1 -r
    echo

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled."
        exit 1
    fi

    echo ""
    install_system_deps
    download_source
    setup_python
    create_configs
    setup_service

    show_complete
}

main "$@"
