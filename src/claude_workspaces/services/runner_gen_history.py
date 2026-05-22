"""Histórico de sessões de geração de runner com Claude.

Cada vez que o usuário clica em 'Gerar com Claude' no dialog de runner,
gravamos {workspace_id, session_id, cwd, hint, created_at} num arquivo
dedicado. Diferente do `session_persistence`, que só salva sessões que
ainda estão *rodando* no fechamento do app, esse índice persiste
independentemente — pra permitir retomar (`claude --resume`) uma sessão
encerrada e pedir mudanças no runner gerado.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from ..claude_sessions import project_sessions_dir
from ..storage import config_dir

log = logging.getLogger(__name__)


def history_file() -> Path:
    return config_dir() / "runner_gen_sessions.json"


@dataclass
class RunnerGenEntry:
    workspace_id: str
    session_id: str
    cwd: str
    hint: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> RunnerGenEntry:
        return cls(
            workspace_id=str(data.get("workspace_id") or ""),
            session_id=str(data.get("session_id") or ""),
            cwd=str(data.get("cwd") or ""),
            hint=str(data.get("hint") or ""),
            created_at=str(data.get("created_at") or ""),
        )

    def is_valid(self) -> bool:
        return bool(self.workspace_id and self.session_id and self.cwd)

    def session_file(self) -> Path:
        return project_sessions_dir(self.cwd) / f"{self.session_id}.jsonl"

    def exists_on_disk(self) -> bool:
        try:
            return self.session_file().exists()
        except OSError:
            return False


def load_history() -> list[RunnerGenEntry]:
    path = history_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.warning("Não consegui ler %s", path)
        return []
    raw = data.get("entries", [])
    if not isinstance(raw, list):
        return []
    out: list[RunnerGenEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        e = RunnerGenEntry.from_dict(item)
        if e.is_valid():
            out.append(e)
    return out


def _save(entries: list[RunnerGenEntry]) -> None:
    path = history_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"entries": [e.to_dict() for e in entries if e.is_valid()]}
    try:
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        log.exception("Falha ao salvar runner-gen history em %s", path)


def add_entry(entry: RunnerGenEntry) -> None:
    """Insere/atualiza por session_id (dedupe)."""
    if not entry.is_valid():
        return
    items = load_history()
    items = [e for e in items if e.session_id != entry.session_id]
    items.append(entry)
    _save(items)


def remove_entry(session_id: str) -> None:
    if not session_id:
        return
    items = [e for e in load_history() if e.session_id != session_id]
    _save(items)


def entries_for_workspace(workspace_id: str) -> list[RunnerGenEntry]:
    """Mais recentes primeiro."""
    items = [e for e in load_history() if e.workspace_id == workspace_id]
    items.sort(key=lambda e: e.created_at, reverse=True)
    return items
