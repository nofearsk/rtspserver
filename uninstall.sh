#!/bin/bash
#
# RTSP to HLS Server - Uninstall Script
#

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${RED}"
echo "╔════════════════════════════════════════════════════════════╗"
echo "║          RTSP to HLS Server - Uninstall                    ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

echo -e "${YELLOW}Warning: This will remove the RTSP Server service.${NC}"
echo ""
read -p "Continue with uninstallation? (y/n) " -n 1 -r
echo

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Uninstallation cancelled."
    exit 1
fi

# Stop PM2 process
echo -e "${YELLOW}Stopping PM2 process...${NC}"
if command -v pm2 &> /dev/null; then
    pm2 stop rtspserver 2>/dev/null || true
    pm2 delete rtspserver 2>/dev/null || true
    pm2 save --force 2>/dev/null || true
fi

# Stop and disable systemd service
echo -e "${YELLOW}Stopping systemd service...${NC}"
if [ -f /etc/systemd/system/rtspserver.service ]; then
    sudo systemctl stop rtspserver 2>/dev/null || true
    sudo systemctl disable rtspserver 2>/dev/null || true
    sudo rm -f /etc/systemd/system/rtspserver.service
    sudo systemctl daemon-reload
fi

# Ask about data deletion
echo ""
read -p "Delete database and stream data? (y/n) " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Removing data...${NC}"
    rm -rf "$INSTALL_DIR/data"
    rm -rf "$INSTALL_DIR/rtspserver.db"
    rm -rf "$INSTALL_DIR/logs"
fi

# Remove generated files
rm -f "$INSTALL_DIR/ecosystem.config.js"
rm -f "$INSTALL_DIR/rtspserver.sh"
rm -f "$INSTALL_DIR/.env"

echo ""
echo -e "${GREEN}Uninstallation complete.${NC}"
echo ""
echo "The following were preserved:"
echo "  - Source code files"
echo "  - Python virtual environment (venv/)"
echo ""
echo "To completely remove, delete the directory:"
echo "  rm -rf $INSTALL_DIR"
