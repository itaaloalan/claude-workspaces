#!/bin/bash
# Imprime tempo decorrido da sessao atual.
# Uso: elapsed.sh <session_id>
set -e

SID="${1:-${CLAUDE_SESSION_ID:-default}}"
FILE="$HOME/.claude/session-state/$SID.json"

if [ ! -f "$FILE" ]; then
  echo "Sessao $SID nao encontrada"
  exit 1
fi

START=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("start",0))' "$FILE" 2>/dev/null || echo 0)
[ "$START" = "0" ] && { echo "Sem timestamp inicial"; exit 1; }

NOW=$(date +%s)
DUR=$((NOW - START))
H=$((DUR / 3600))
M=$(((DUR % 3600) / 60))
S=$((DUR % 60))

printf '%dh %02dm %02ds\n' "$H" "$M" "$S"
