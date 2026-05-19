#!/usr/bin/env bash
# install/install.sh
# Installs omenfancontrol to /opt/omenfancontrol and sets up systemd service.
#
# Usage:
#   sudo bash install/install.sh
#
# Requirements:
#   Python 3.11+, power-profiles-daemon, nvidia-smi (optional)

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
FAN_PWM_PATH="/sys/devices/platform/hp-wmi/hwmon/hwmon5/pwm1_enable"

echo ""
echo -e "${ORANGE}  OMEN FAN CONTROL  installer${NC}"
echo ""

if [[ $EUID -ne 0 ]]; then
    fail "run as root: sudo bash install/install.sh"
fi

info "checking Python version..."
if command -v python3.11 &>/dev/null; then
    PYTHON_BIN=$(which python3.11)
else
    PYTHON_BIN=$(which python3)
fi

PYTHON_VERSION=$($PYTHON_BIN -c \
    "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [[ $PYTHON_MAJOR -lt 3 || ($PYTHON_MAJOR -eq 3 && $PYTHON_MINOR -lt 11) ]]; then
    fail "Python 3.11+ required, found $PYTHON_VERSION"
fi
ok "Python $PYTHON_VERSION ($PYTHON_BIN)"

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

info "copying project files..."
rsync -a \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='tests/' \
    --exclude='*.egg-info' \
    --exclude='dist/' \
    --exclude='build/' \
    ./ "$INSTALL_DIR/"
ok "files copied to $INSTALL_DIR"

info "installing python3-venv..."
apt-get install -y "python3.${PYTHON_MINOR}-venv" \
    --no-install-recommends -qq 2>/dev/null \
    || apt-get install -y python3-venv \
    --no-install-recommends -qq
ok "python3-venv ready"

info "creating virtual environment..."
$PYTHON_BIN -m venv "$INSTALL_DIR/.venv"
ok "virtualenv created ($PYTHON_VERSION)"

info "installing dependencies..."
"$INSTALL_DIR/.venv/bin/pip" install --upgrade pip --quiet
"$INSTALL_DIR/.venv/bin/pip" install PyQt6 --quiet
ok "dependencies installed"

info "creating data directory..."
mkdir -p "$DATA_DIR"
chmod 755 "$DATA_DIR"
ok "data directory: $DATA_DIR"

info "installing systemd service..."
cp "$INSTALL_DIR/install/omenfancontrol.service" "$SERVICE_FILE"
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
cp "$INSTALL_DIR/install/omenfancontrol-gui.desktop" \
    "/usr/share/applications/omenfancontrol.desktop"
chmod 644 "/usr/share/applications/omenfancontrol.desktop"
ok "desktop entry installed"

info "creating GUI launcher..."
cat > "/usr/local/bin/omenfancontrol" <<EOF
#!/usr/bin/env bash
cd /opt/omenfancontrol
exec /opt/omenfancontrol/.venv/bin/python3 /opt/omenfancontrol/main.py "\$@"
EOF
chmod +x "/usr/local/bin/omenfancontrol"
ok "launcher: /usr/local/bin/omenfancontrol"

echo ""
read -r -p "  Enable GUI autostart on login for $CURRENT_USER? [y/N] " response
if [[ "$response" =~ ^[Yy]$ ]]; then
    AUTOSTART_DIR="/home/$CURRENT_USER/.config/autostart"
    mkdir -p "$AUTOSTART_DIR"
    cp "$INSTALL_DIR/install/omenfancontrol-autostart.desktop" \
       "$AUTOSTART_DIR/omenfancontrol.desktop"
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
echo "  uninstall     : sudo bash $INSTALL_DIR/install/uninstall.sh"
echo ""