"""Inspector dos hooks configurados do Claude Code.

Lê settings.json em 3 escopos:
- user:        ~/.claude/settings.json
- project:     <ws>/.claude/settings.json
- local:       <ws>/.claude/settings.local.json (gitignored)

Schema esperado:
{
  "hooks": {
    "Stop": [
      {"matcher": "pattern_regex", "hooks": [
         {"type": "command", "command": "shell ...", "timeout": 30}
      ]}
    ],
    "PostToolUse": [...], ...
  }
}

Devolve uma lista flat de HookEntry pra render em tabela.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

HOOK_EVENTS = (
    "PreToolUse",
    "PostToolUse",
    "Stop",
    "SubagentStop",
    "Notification",
    "UserPromptSubmit",
)

SCOPE_USER = "user"
SCOPE_PROJECT = "project"
SCOPE_LOCAL = "local"


@dataclass(frozen=True)
class HookEntry:
    scope: str          # "user" | "project" | "local"
    event: str          # "Stop", "PostToolUse", etc
    matcher: str        # padrão (vazio = qualquer)
    command: str        # comando shell
    type_: str          # "command" geralmente
    timeout: int | None
    source_file: Path

    def short_command(self) -> str:
        cmd = self.command.replace("\n", " ").strip()
        if len(cmd) > 80:
            return cmd[:79] + "…"
        return cmd


def _load_settings(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.debug("Skip %s: %s", path, e)
        return {}


def _entries_from(settings: dict, scope: str, source_file: Path) -> list[HookEntry]:
    out: list[HookEntry] = []
    hooks_root = settings.get("hooks")
    if not isinstance(hooks_root, dict):
        return out
    for event, event_entries in hooks_root.items():
        if not isinstance(event_entries, list):
            continue
        for entry in event_entries:
            if not isinstance(entry, dict):
                continue
            matcher = str(entry.get("matcher", "") or "")
            inner = entry.get("hooks", [])
            if not isinstance(inner, list):
                continue
            for h in inner:
                if not isinstance(h, dict):
                    continue
                cmd = str(h.get("command", "") or "")
                if not cmd:
                    continue
                timeout = h.get("timeout")
                if not isinstance(timeout, int):
                    timeout = None
                out.append(HookEntry(
                    scope=scope,
                    event=str(event),
                    matcher=matcher,
                    command=cmd,
                    type_=str(h.get("type", "command") or "command"),
                    timeout=timeout,
                    source_file=source_file,
                ))
    return out


def list_hooks(workspace_folders: list[str] | None = None) -> list[HookEntry]:
    """Coleta hooks de user + project + local em ordem de prioridade.

    workspace_folders: pastas do workspace ativo. Hooks de project/local
    são lidos da primeira pasta (convenção: cwd primário).
    """
    entries: list[HookEntry] = []
    user_file = Path.home() / ".claude" / "settings.json"
    if user_file.exists():
        entries.extend(_entries_from(_load_settings(user_file), SCOPE_USER, user_file))
    if workspace_folders:
        first = Path(workspace_folders[0])
        for fname, scope in (
            ("settings.json", SCOPE_PROJECT),
            ("settings.local.json", SCOPE_LOCAL),
        ):
            f = first / ".claude" / fname
            if f.exists():
                entries.extend(_entries_from(_load_settings(f), scope, f))
    return entries


def group_by_event(entries: list[HookEntry]) -> dict[str, list[HookEntry]]:
    out: dict[str, list[HookEntry]] = {}
    for e in entries:
        out.setdefault(e.event, []).append(e)
    # Ordem natural: eventos conhecidos primeiro, na ordem do tuple
    ordered: dict[str, list[HookEntry]] = {}
    for ev in HOOK_EVENTS:
        if ev in out:
            ordered[ev] = out[ev]
    for ev, items in out.items():
        if ev not in ordered:
            ordered[ev] = items
    return ordered
