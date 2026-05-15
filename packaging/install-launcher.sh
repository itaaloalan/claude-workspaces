#!/usr/bin/env bash
# Instala o launcher .desktop e o ícone do Claude Workspaces no menu do KDE.
# Detecta automaticamente como o app está rodando (pipx, venv local, ou source).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

APP_NAME="claude-workspaces"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS_BASE="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
ICONS_DIR="$ICONS_BASE/scalable/apps"

mkdir -p "$APPS_DIR" "$ICONS_DIR"

EXEC_CMD=""
if command -v claude-workspaces >/dev/null 2>&1; then
    EXEC_CMD="$(command -v claude-workspaces)"
    echo "  → Detectado entrypoint instalado: $EXEC_CMD"
elif [ -x "$REPO_ROOT/.venv/bin/claude-workspaces" ]; then
    EXEC_CMD="$REPO_ROOT/.venv/bin/claude-workspaces"
    echo "  → Detectado venv local: $EXEC_CMD"
elif [ -x "$REPO_ROOT/.venv/bin/python" ]; then
    EXEC_CMD="$REPO_ROOT/.venv/bin/python -m claude_workspaces"
    echo "  → Detectado venv local sem entrypoint, usando python -m"
else
    EXEC_CMD="env PYTHONPATH=$REPO_ROOT/src python3 -m claude_workspaces"
    echo "  → Sem venv detectado, rodando direto do source via PYTHONPATH"
fi

DESKTOP_FILE="$APPS_DIR/$APP_NAME.desktop"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Claude Workspaces
GenericName=Workspace Manager
Comment=Gerencie workspaces e abra o Claude Code com contexto isolado por projeto
Exec=$EXEC_CMD
Path=$REPO_ROOT
Icon=$APP_NAME
Terminal=false
Categories=Development;Utility;IDE;
StartupNotify=true
StartupWMClass=$APP_NAME
Keywords=claude;workspace;ai;projects;dev;
EOF

cp "$SCRIPT_DIR/$APP_NAME.svg" "$ICONS_DIR/"

update-desktop-database "$APPS_DIR" 2>/dev/null || true
gtk-update-icon-cache "$ICONS_BASE" 2>/dev/null || true
kbuildsycoca6 --noincremental 2>/dev/null \
    || kbuildsycoca5 --noincremental 2>/dev/null \
    || true

echo ""
echo "✓ Launcher: $DESKTOP_FILE"
echo "✓ Ícone:    $ICONS_DIR/$APP_NAME.svg"
echo "✓ Exec:     $EXEC_CMD"
echo ""
echo "Procure por 'Claude Workspaces' no menu iniciar do KDE."
echo "Para desinstalar: $SCRIPT_DIR/uninstall-launcher.sh"
