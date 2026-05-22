#!/bin/bash
# SessionEnd hook: imprime duracao total da sessao.
set -e

STATE_DIR="$HOME/.claude/session-state"
LOG="$HOME/.claude/session-state/durations.log"

INPUT=$(cat 2>/dev/null || true)
SID=""
if [ -n "$INPUT" ]; then
  SID=$(printf '%s' "$INPUT" | python3 -c 'import json,sys;d=json.load(sys.stdin) if sys.stdin else {};print(d.get("session_id",""))' 2>/dev/null || true)
fi
[ -z "$SID" ] && SID="${CLAUDE_SESSION_ID:-default}"

FILE="$STATE_DIR/$SID.json"
[ ! -f "$FILE" ] && exit 0

START=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("start",0))' "$FILE" 2>/dev/null || echo 0)
[ "$START" = "0" ] && exit 0

NOW=$(date +%s)
DUR=$((NOW - START))
H=$((DUR / 3600))
M=$(((DUR % 3600) / 60))
S=$((DUR % 60))

STAMP=$(date '+%Y-%m-%d %H:%M:%S')
printf '[%s] session %s: %dh %02dm %02ds (cwd=%s)\n' "$STAMP" "$SID" "$H" "$M" "$S" "$PWD" >> "$LOG"

# Imprime para stdout (visivel no fim da sessao em alguns clientes)
printf 'Sessao durou: %dh %02dm %02ds\n' "$H" "$M" "$S"

exit 0
