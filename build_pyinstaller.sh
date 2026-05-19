#!/usr/bin/env bash
# build_pyinstaller.sh
# Builds a self-contained binary tarball using PyInstaller.
#
# Usage:
#   bash build_pyinstaller.sh
#
# Output:
#   omenfancontrol-<version>-linux-x86_64.tar.gz

set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "${GREEN}  ok${NC}  $*"; }
info() { echo -e "${BLUE}  ..${NC}  $*"; }
fail() { echo -e "${RED}  fail${NC}  $*"; exit 1; }

VERSION=$(python3 -c "
import tomllib
with open('pyproject.toml', 'rb') as f:
    data = tomllib.load(f)
print(data['project']['version'])
")

TARBALL="omenfancontrol-${VERSION}-linux-x86_64.tar.gz"
RELEASE_DIR="omenfancontrol-${VERSION}"

echo ""
echo -e "${BLUE}  OMEN FAN CONTROL  PyInstaller builder${NC}"
echo ""
echo "  version : $VERSION"
echo "  output  : $TARBALL"
echo ""

command -v pyinstaller &>/dev/null || fail "pyinstaller not found — pip install pyinstaller"
[[ -f "omenfancontrol.spec" ]] || fail "omenfancontrol.spec not found"

info "cleaning previous build..."
rm -rf dist/ build/ "$RELEASE_DIR" "$TARBALL"
ok "clean"

info "building with PyInstaller..."
pyinstaller omenfancontrol.spec --clean --noconfirm
ok "PyInstaller build complete"

# verify both binaries exist before packaging
info "verifying binaries..."
[[ -f "dist/omenfancontrol/omenfancontrol-gui" ]] \
    || fail "omenfancontrol-gui not found"
[[ -f "dist/omenfancontrol/omenfancontrol-daemon" ]] \
    || fail "omenfancontrol-daemon not found"
ok "binaries verified"

info "packaging tarball..."
mkdir -p "$RELEASE_DIR"

# copy self-contained binaries and shared libraries from PyInstaller output
cp -r dist/omenfancontrol/* "$RELEASE_DIR/"

# copy installer — uses binary-aware service file (no Python needed)
cp install/install_binary.sh      "$RELEASE_DIR/install.sh"
cp install/uninstall.sh           "$RELEASE_DIR/uninstall.sh"
cp install/omenfancontrol-gui.desktop "$RELEASE_DIR/"

# write the binary-aware service file directly into the release directory
# ExecStart points to the binary, not a Python interpreter
cat > "$RELEASE_DIR/omenfancontrol.service" <<EOF
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

tar -czf "$TARBALL" "$RELEASE_DIR/"
ok "tarball created: $TARBALL"

SIZE=$(du -sh "$TARBALL" | cut -f1)
rm -rf "$RELEASE_DIR"

echo ""
echo -e "${GREEN}  build complete${NC}"
echo ""
echo "  file    : $TARBALL"
echo "  size    : $SIZE"
echo ""
echo "  install:"
echo "    tar -xzf $TARBALL"
echo "    cd $RELEASE_DIR"
echo "    sudo bash install.sh"
echo ""