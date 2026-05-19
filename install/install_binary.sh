#!/usr/bin/env bash
# install/install_binary.sh
# Installs pre-built binaries (PyInstaller) to /opt/omenfancontrol.
# No Python or pip required — binaries are self-contained.
#
# Usage:
#   sudo bash install.sh
#
# Requirements:
#   power-profiles-daemon, nvidia-smi (optional)

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
ORANGE='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ok()   { echo -e "${GREEN}  ok${NC}  $*"; }
fail() { echo -e "${RED}  fail${NC}  $*"; exit 1; }
info() { echo -e "${BLUE}  ..${NC}  $*"; }
warn() { echo -e "${ORANGE}  warn${NC}  $*"; }

INSTALL_DIR="/opt/omenfancontrol"
SERVICE_NAME="omenfancontrol"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
DATA_DIR="/var/lib/omenfancontrol"
CURRENT_USER="${SUDO_USER:-$USER}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FAN_PWM_PATH="/sys/devices/platform/hp-wmi/hwmon/hwmon5/pwm1_enable"

echo ""
echo -e "${ORANGE}  OMEN FAN CONTROL  binary installer${NC}"
echo ""

if [[ $EUID -ne 0 ]]; then
    fail "run as root: sudo bash install.sh"
fi

# verify both binaries exist before doing anything
GUI_BIN="$SCRIPT_DIR/omenfancontrol-gui"
DAEMON_BIN="$SCRIPT_DIR/omenfancontrol-daemon"

info "detecting binaries..."
[[ -f "$GUI_BIN" ]]    || fail "omenfancontrol-gui not found in $SCRIPT_DIR"
[[ -f "$DAEMON_BIN" ]] || fail "omenfancontrol-daemon not found in $SCRIPT_DIR"
ok "gui binary: $GUI_BIN"
ok "daemon binary: $DAEMON_BIN"

info "checking fan control interface..."
if [[ -f "$FAN_PWM_PATH" ]]; then
    ok "fan control: $FAN_PWM_PATH"
else
    warn "fan control path not found — may not work on this model"
fi

info "checking power-profiles-daemon..."
if command -v powerprofilesctl &>/dev/null; then
    ok "powerprofilesctl found"
else
    warn "powerprofilesctl not found — power profiles unavailable"
fi

info "checking nvidia-smi..."
if command -v nvidia-smi &>/dev/null; then
    ok "nvidia-smi found"
else
    warn "nvidia-smi not found — GPU metrics unavailable"
fi

info "creating install directory..."
mkdir -p "$INSTALL_DIR"

# copy all release files except the installer and uninstaller
# the daemon binary runs as root via systemd so it can write to /sys directly
info "copying binaries and assets..."
rsync -a \
    --exclude='install.sh' \
    --exclude='uninstall.sh' \
    "$SCRIPT_DIR/" "$INSTALL_DIR/"

chmod +x "$INSTALL_DIR/omenfancontrol-gui"
chmod +x "$INSTALL_DIR/omenfancontrol-daemon"
ok "binaries installed to $INSTALL_DIR"

# copy uninstall script so user can remove from the install location
cp "$SCRIPT_DIR/uninstall.sh" "$INSTALL_DIR/uninstall.sh"
chmod +x "$INSTALL_DIR/uninstall.sh"
ok "uninstall script installed"

info "creating data directory..."
mkdir -p "$DATA_DIR"
chmod 755 "$DATA_DIR"
ok "data directory: $DATA_DIR"

# write the service file inline — the binary path is fixed so no
# Python interpreter is needed in ExecStart
info "installing systemd service..."
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=OMEN Fan Control Daemon
Documentation=https://github.com/AbdulRahman2257/omenfancontrol
After=multi-user.target
Wants=multi-user.target

[Service]
Type=simple
ExecStart=/opt/omenfancontrol/omenfancontrol-daemon
WorkingDirectory=/opt/omenfancontrol
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=omenfancontrol

[Install]
WantedBy=multi-user.target
EOF
chmod 644 "$SERVICE_FILE"
ok "service file: $SERVICE_FILE"

info "enabling and starting service..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl start  "$SERVICE_NAME"

sleep 2

if systemctl is-active --quiet "$SERVICE_NAME"; then
    ok "daemon is running"
else
    warn "daemon failed to start"
    warn "check logs: journalctl -u $SERVICE_NAME -n 20"
fi

info "installing desktop entry..."
cat > /usr/share/applications/omenfancontrol.desktop <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=OMEN Dashboard
Comment=Fan and thermal control dashboard for HP OMEN laptops
Exec=/opt/omenfancontrol/omenfancontrol-gui
Icon=utilities-system-monitor
Terminal=false
Categories=System;Monitor;
Keywords=fan;thermal;omen;hp;
StartupNotify=true
EOF
chmod 644 /usr/share/applications/omenfancontrol.desktop
ok "desktop entry installed"

info "creating GUI launcher..."
cat > /usr/local/bin/omenfancontrol <<EOF
#!/usr/bin/env bash
exec /opt/omenfancontrol/omenfancontrol-gui "\$@"
EOF
chmod +x /usr/local/bin/omenfancontrol
ok "launcher: /usr/local/bin/omenfancontrol"

echo ""
read -r -p "  Enable GUI autostart on login for $CURRENT_USER? [y/N] " response
if [[ "$response" =~ ^[Yy]$ ]]; then
    AUTOSTART_DIR="/home/$CURRENT_USER/.config/autostart"
    mkdir -p "$AUTOSTART_DIR"
    cat > "$AUTOSTART_DIR/omenfancontrol.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=OMEN Dashboard
Exec=/opt/omenfancontrol/omenfancontrol-gui
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Comment=Start OMEN Dashboard on login
EOF
    chown "$CURRENT_USER:$CURRENT_USER" \
          "$AUTOSTART_DIR/omenfancontrol.desktop"
    ok "autostart enabled for $CURRENT_USER"
else
    info "autostart skipped"
fi

echo ""
echo -e "${GREEN}  installation complete${NC}"
echo ""
echo "  daemon status : systemctl status $SERVICE_NAME"
echo "  daemon logs   : journalctl -u $SERVICE_NAME -f"
echo "  launch GUI    : omenfancontrol"
echo "  uninstall     : sudo bash /opt/omenfancontrol/uninstall.sh"
echo ""