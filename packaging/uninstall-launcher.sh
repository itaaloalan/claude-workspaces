#!/usr/bin/env bash
# Remove o launcher .desktop e o ícone do Claude Workspaces.

set -euo pipefail

APP_NAME="claude-workspaces"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS_BASE="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
ICONS_DIR="$ICONS_BASE/scalable/apps"

rm -f "$APPS_DIR/$APP_NAME.desktop"
rm -f "$ICONS_DIR/$APP_NAME.svg"

update-desktop-database "$APPS_DIR" 2>/dev/null || true
gtk-update-icon-cache "$ICONS_BASE" 2>/dev/null || true
kbuildsycoca6 --noincremental 2>/dev/null \
    || kbuildsycoca5 --noincremental 2>/dev/null \
    || true

echo "✓ Launcher e ícone removidos do menu."
