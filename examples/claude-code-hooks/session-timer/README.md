# session-timer

Hooks nativos do Claude Code (CLI) que medem a duração de cada sessão.

Não é um plugin do Claude Workspaces — são scripts bash registrados como
hooks `SessionStart` / `SessionEnd` no `~/.claude/settings.json` do próprio
Claude Code. Funciona independente do Workspaces.

## Como funciona

- `start.sh` (hook `SessionStart`): grava o timestamp inicial em
  `~/.claude/session-state/<session_id>.json` quando uma sessão abre.
  Não sobrescreve se o arquivo já existe (preserva o start em retomadas
  ou após compactação de contexto).
- `end.sh` (hook `SessionEnd`): lê o timestamp inicial, calcula a duração,
  imprime `Sessao durou: Xh Ymm Zss` e anexa em
  `~/.claude/session-state/durations.log`.
- `elapsed.sh <session_id>`: utilitário CLI pra perguntar "quanto tempo
  já passou nessa sessão?" sem encerrar. Útil em statusline ou comando
  manual.

O `session_id` é lido do JSON que o Claude Code passa no stdin do hook
(campo `session_id`). Cai pra `$CLAUDE_SESSION_ID` ou `default` se não
vier.

## Instalação

```bash
mkdir -p ~/.claude/scripts/session-timer
cp start.sh end.sh elapsed.sh ~/.claude/scripts/session-timer/
chmod +x ~/.claude/scripts/session-timer/*.sh
```

Adicione em `~/.claude/settings.json` (preservando hooks existentes):

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [ { "type": "command", "command": "/home/USER/.claude/scripts/session-timer/start.sh" } ] }
    ],
    "SessionEnd": [
      { "hooks": [ { "type": "command", "command": "/home/USER/.claude/scripts/session-timer/end.sh" } ] }
    ]
  }
}
```

Troque `USER` pelo seu home real.

## Uso

Pergunte em qualquer momento:

```bash
~/.claude/scripts/session-timer/elapsed.sh "$CLAUDE_SESSION_ID"
# 0h 47m 12s
```

Ao fechar a sessão, o `end.sh` imprime a duração e acumula em
`~/.claude/session-state/durations.log`:

```
[2026-05-22 15:39:38] session abc123: 0h 50m 35s (cwd=/home/italo/Projetos/...)
```

## Por que não como plugin do Workspaces

Esses hooks rodam dentro do processo do `claude` CLI — antes mesmo de
qualquer evento do Workspaces. Reescrever como plugin Python (spec v2)
deixaria a contagem dependente do Workspaces estar rodando, o que
limitaria o uso. Como hook nativo, funciona em qualquer terminal onde
o Claude Code abrir.

Um plugin do Workspaces poderia ler o `durations.log` gerado por esses
scripts pra mostrar histórico/agregar por workspace — fica de extensão
futura.
