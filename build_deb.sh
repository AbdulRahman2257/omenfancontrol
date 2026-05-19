#!/usr/bin/env bash
# build_deb.sh
# Builds a .deb package from the current source tree.
#
# Usage:
#   bash build_deb.sh
#
# Output:
#   omenfancontrol_<version>_amd64.deb

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

PKG="omenfancontrol_${VERSION}_amd64"

echo ""
echo -e "${BLUE}  OMEN FAN CONTROL  deb builder${NC}"
echo ""
echo "  version : $VERSION"
echo "  package : $PKG.deb"
echo ""

command -v dpkg-deb &>/dev/null || fail "dpkg-deb not found — install dpkg"
command -v rsync    &>/dev/null || fail "rsync not found — sudo apt install rsync"

[[ -f "install/debian/control"   ]] || fail "install/debian/control missing"
[[ -f "install/debian/postinst"  ]] || fail "install/debian/postinst missing"
[[ -f "install/debian/prerm"     ]] || fail "install/debian/prerm missing"
[[ -f "install/debian/copyright" ]] || fail "install/debian/copyright missing"

info "cleaning previous build..."
rm -rf "$PKG" "${PKG}.deb"
ok "clean"

info "creating package structure..."
mkdir -p "$PKG/DEBIAN"
mkdir -p "$PKG/opt/omenfancontrol"
ok "structure created"

# exclude build artifacts, caches, and previous deb files
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
    --exclude='*.deb' \
    --exclude="omenfancontrol_*" \
    ./ "$PKG/opt/omenfancontrol/"
ok "project files copied"

# postinst runs after apt install — creates venv, installs PyQt6, starts daemon
info "copying debian control files..."
cp install/debian/control   "$PKG/DEBIAN/control"
cp install/debian/postinst  "$PKG/DEBIAN/postinst"
cp install/debian/prerm     "$PKG/DEBIAN/prerm"
cp install/debian/copyright "$PKG/DEBIAN/copyright"
chmod 755 "$PKG/DEBIAN/postinst"
chmod 755 "$PKG/DEBIAN/prerm"

# stamp the version into the control file from pyproject.toml
sed -i "s/^Version:.*/Version: ${VERSION}/" "$PKG/DEBIAN/control"
ok "debian control files ready"

info "building .deb package..."
dpkg-deb --build --root-owner-group "$PKG"
ok "package built: ${PKG}.deb"

SIZE=$(du -sh "${PKG}.deb" | cut -f1)

# remove the staging directory — only the .deb is needed
rm -rf "$PKG"

echo ""
echo -e "${GREEN}  build complete${NC}"
echo ""
echo "  file    : ${PKG}.deb"
echo "  size    : $SIZE"
echo ""
echo "  install : sudo apt install ./${PKG}.deb"
echo "  remove  : sudo apt remove omenfancontrol"
echo "  purge   : sudo apt purge omenfancontrol"
echo ""