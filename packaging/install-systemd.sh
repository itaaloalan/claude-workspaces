#!/usr/bin/env bash
# Instala uma systemd user unit que mantém o Claude Workspaces rodando
# em background (no tray) entre sessões gráficas. Quando combinado com
# um atalho global do desktop env (KDE/GNOME/Hyprland) que dispara
# `claude-workspaces-focus`, dá pra trazer o app pra frente sem alt-tab.
#
# Uso:
#   ./packaging/install-systemd.sh           # instala e habilita
#   ./packaging/install-systemd.sh --remove  # desinstala

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
UNIT_NAME="claude-workspaces.service"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_FILE="$UNIT_DIR/$UNIT_NAME"
FOCUS_BIN="$HOME/.local/bin/claude-workspaces-focus"

# Detecta executável (mesma lógica do install-launcher.sh)
detect_exec() {
    if command -v claude-workspaces >/dev/null 2>&1; then
        command -v claude-workspaces
    elif [ -x "$REPO_ROOT/.venv/bin/claude-workspaces" ]; then
        echo "$REPO_ROOT/.venv/bin/claude-workspaces"
    elif [ -x "$REPO_ROOT/.venv/bin/python" ]; then
        echo "$REPO_ROOT/.venv/bin/python -m claude_workspaces"
    else
        echo "env PYTHONPATH=$REPO_ROOT/src python3 -m claude_workspaces"
    fi
}

if [ "${1:-}" = "--remove" ]; then
    systemctl --user disable --now "$UNIT_NAME" 2>/dev/null || true
    rm -f "$UNIT_FILE" "$FOCUS_BIN"
    systemctl --user daemon-reload
    echo "✓ Unit + focus helper removidos."
    exit 0
fi

EXEC_CMD="$(detect_exec)"
echo "  → Exec: $EXEC_CMD"

mkdir -p "$UNIT_DIR" "$HOME/.local/bin"

# Substitui o ExecStart padrão pelo comando detectado
sed "s|%h/.local/bin/claude-workspaces|$EXEC_CMD|" \
    "$SCRIPT_DIR/$UNIT_NAME" > "$UNIT_FILE"

# Helper script pra trazer o app pra frente. Usa wmctrl/xdotool se
# disponível, caso contrário tenta `kdotool` (Wayland-KDE) ou abre o
# launcher do .desktop pra ativar via single-instance.
cat > "$FOCUS_BIN" <<'EOF'
#!/usr/bin/env bash
# Trazer o Claude Workspaces pra frente. Bind isso num atalho global
# do seu desktop (System Settings → Shortcuts → Custom).
set -e
WMCLASS="claude-workspaces"

if command -v wmctrl >/dev/null 2>&1; then
    wmctrl -x -a "$WMCLASS" && exit 0
fi
if command -v xdotool >/dev/null 2>&1; then
    win=$(xdotool search --class "$WMCLASS" | head -1) || true
    if [ -n "$win" ]; then
        xdotool windowactivate "$win" && exit 0
    fi
fi
if command -v kdotool >/dev/null 2>&1; then
    kdotool search --class "$WMCLASS" --activate && exit 0
fi
# Fallback: rodar o launcher novamente — single-instance no Qt traz pra frente
exec "$@"
EOF
chmod +x "$FOCUS_BIN"

systemctl --user daemon-reload
systemctl --user enable --now "$UNIT_NAME"

echo ""
echo "✓ Unit instalada:  $UNIT_FILE"
echo "✓ Focus helper:    $FOCUS_BIN"
echo ""
echo "Status:"
systemctl --user status "$UNIT_NAME" --no-pager -l | head -6 || true
echo ""
echo "Para ligar atalho global:"
echo "  KDE   → System Settings → Shortcuts → Add Command → '$FOCUS_BIN'"
echo "  GNOME → Settings → Keyboard → Custom Shortcuts"
echo "  Hyprland/Sway → bind = SUPER, J, exec, $FOCUS_BIN"
echo ""
echo "Para desinstalar: $SCRIPT_DIR/install-systemd.sh --remove"
