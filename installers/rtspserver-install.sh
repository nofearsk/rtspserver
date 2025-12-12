#!/bin/bash
#
# RTSP to HLS Server - One-Line Installer
#
# Usage:
#   bash <(curl -s https://raw.githubusercontent.com/YOUR_REPO/rtspserver/main/installers/rtspserver-install.sh)
#
# Or with options:
#   bash <(curl -s ...) --branch develop --dir /opt/rtspserver
#

set -e

# Default values
REPO_URL="https://github.com/YOUR_USERNAME/rtspserver.git"
BRANCH="main"
INSTALL_DIR="/opt/rtspserver"
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
    echo -e "${BLUE}[1/6] Installing system dependencies...${NC}"

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

# Install Node.js and PM2
install_nodejs_pm2() {
    echo -e "${BLUE}[2/6] Installing Node.js and PM2...${NC}"

    # Install Node.js if not present
    if ! command -v node &> /dev/null; then
        case $OS in
            ubuntu|debian)
                curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash - > /dev/null 2>&1
                sudo apt-get install -y -qq nodejs > /dev/null
                ;;
            centos|rhel|rocky|almalinux|fedora)
                curl -fsSL https://rpm.nodesource.com/setup_18.x | sudo bash - > /dev/null 2>&1
                sudo dnf install -y -q nodejs
                ;;
            arch|manjaro)
                sudo pacman -S --noconfirm --quiet nodejs npm
                ;;
        esac
    fi

    # Install PM2
    if ! command -v pm2 &> /dev/null; then
        sudo npm install -g pm2 > /dev/null 2>&1
    fi

    echo -e "${GREEN}✓ Node.js $(node --version) and PM2 installed${NC}"
}

# Clone or download repository
download_source() {
    echo -e "${BLUE}[3/6] Downloading RTSP Server...${NC}"

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

# Setup Python environment
setup_python() {
    echo -e "${BLUE}[4/6] Setting up Python environment...${NC}"

    cd "$INSTALL_DIR"

    # Create virtual environment
    python3 -m venv venv

    # Activate and install dependencies
    source venv/bin/activate
    pip install --upgrade pip -q
    pip install -r requirements.txt -q

    echo -e "${GREEN}✓ Python environment ready${NC}"
}

# Create configuration files
create_configs() {
    echo -e "${BLUE}[5/6] Creating configuration files...${NC}"

    cd "$INSTALL_DIR"

    # Create directories
    mkdir -p data/streams logs

    # Create .env if not exists
    if [ ! -f .env ]; then
        cat > .env << EOF
HOST=0.0.0.0
PORT=8000
DEBUG=false
DATABASE_PATH=./data/rtspserver.db
STREAMS_DIR=./data/streams
SECRET_KEY=$(openssl rand -hex 32)
EOF
    fi

    # Create PM2 ecosystem file
    cat > ecosystem.config.js << 'EOF'
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
    time: true
  }]
};
EOF

    # Create management script
    cat > rtspserver << 'MGMT'
#!/bin/bash
cd "$(dirname "$0")"

case "$1" in
    start)   pm2 start ecosystem.config.js ;;
    stop)    pm2 stop rtspserver ;;
    restart) pm2 restart rtspserver ;;
    status)  pm2 status rtspserver ;;
    logs)    pm2 logs rtspserver --lines 100 ;;
    monitor) pm2 monit ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs|monitor}"
        exit 1
        ;;
esac
MGMT
    chmod +x rtspserver

    # Create symlink for easy access
    sudo ln -sf "$INSTALL_DIR/rtspserver" /usr/local/bin/rtspserver 2>/dev/null || true

    echo -e "${GREEN}✓ Configuration files created${NC}"
}

# Start server and setup autostart
start_server() {
    echo -e "${BLUE}[6/6] Starting server...${NC}"

    cd "$INSTALL_DIR"

    # Start with PM2
    pm2 start ecosystem.config.js

    # Setup startup script
    pm2 startup -u "${SUDO_USER:-$(whoami)}" --hp "${HOME:-/root}" > /dev/null 2>&1 || true
    pm2 save > /dev/null 2>&1

    echo -e "${GREEN}✓ Server started and autostart configured${NC}"
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
    echo -e "${CYAN}Or use PM2 directly:${NC}"
    echo "  pm2 logs rtspserver"
    echo "  pm2 monit"
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
    install_nodejs_pm2
    download_source
    setup_python
    create_configs

    if [ "$AUTO_START" = "yes" ]; then
        start_server
    fi

    show_complete
}

main "$@"
