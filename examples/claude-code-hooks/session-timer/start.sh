#!/bin/bash
# SessionStart hook: registra timestamp inicial da sessao.
# Recebe JSON via stdin com { "session_id": "...", ... }
set -e

STATE_DIR="$HOME/.claude/session-state"
mkdir -p "$STATE_DIR"

# Tenta extrair session_id do JSON do stdin; fallback para variavel de ambiente.
INPUT=$(cat 2>/dev/null || true)
SID=""
if [ -n "$INPUT" ]; then
  SID=$(printf '%s' "$INPUT" | python3 -c 'import json,sys;d=json.load(sys.stdin) if sys.stdin else {};print(d.get("session_id",""))' 2>/dev/null || true)
fi
[ -z "$SID" ] && SID="${CLAUDE_SESSION_ID:-default}"

NOW=$(date +%s)
FILE="$STATE_DIR/$SID.json"

# So escreve se ainda nao existir (preserva start em retomadas/compact)
if [ ! -f "$FILE" ]; then
  printf '{"start":%s,"session_id":"%s","cwd":"%s"}\n' "$NOW" "$SID" "$PWD" > "$FILE"
fi

exit 0
