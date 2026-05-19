#!/usr/bin/env bash
# install/uninstall.sh
# Removes omenfancontrol and all installed files.
#
# Usage:
#   sudo bash uninstall.sh

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
ORANGE='\033[0;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}  ok${NC}  $*"; }
info() { echo -e "${BLUE}  ..${NC}  $*"; }
warn() { echo -e "${ORANGE}  warn${NC}  $*"; }

INSTALL_DIR="/opt/omenfancontrol"
SERVICE_NAME="omenfancontrol"
CURRENT_USER="${SUDO_USER:-$USER}"

echo ""
echo -e "${RED}  OMEN FAN CONTROL  uninstaller${NC}"
echo ""

if [[ $EUID -ne 0 ]]; then
    echo "run as root: sudo bash uninstall.sh"
    exit 1
fi

info "stopping daemon..."
systemctl stop    "$SERVICE_NAME" 2>/dev/null || true
systemctl disable "$SERVICE_NAME" 2>/dev/null || true
rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
ok "service removed"

# remove install directory — contains all binaries and source files
info "removing install directory..."
rm -rf "$INSTALL_DIR"
ok "install directory removed"

# desktop entries and launcher
info "removing desktop entries and launcher..."
rm -f "/usr/share/applications/omenfancontrol.desktop"
rm -f "/home/$CURRENT_USER/.config/autostart/omenfancontrol.desktop"
rm -f "/usr/local/bin/omenfancontrol"
ok "desktop entries and launcher removed"

# thresholds are stored separately — ask before removing
echo ""
read -r -p "  Remove saved thresholds in /var/lib/omenfancontrol? [y/N] " response
if [[ "$response" =~ ^[Yy]$ ]]; then
    rm -rf "/var/lib/omenfancontrol"
    ok "data directory removed"
else
    info "data directory kept at /var/lib/omenfancontrol"
fi

echo ""
echo -e "${GREEN}  uninstall complete${NC}"
echo ""