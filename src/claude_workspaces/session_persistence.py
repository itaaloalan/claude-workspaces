"""Persiste sessões Claude ativas entre execuções.

No closeEvent, salva a lista de tabs Claude rodando (workspace_id +
session_id + cwd). No próximo startup, restaura cada uma via
`claude --resume <session_id>` no terminal embutido, recriando as abas
no mesmo workspace.

Não persiste shells nem tabs que ainda não resolveram o JSONL — só
salvamos quando o TerminalWidget já tem `_claimed_session_id`, garantindo
que o `--resume` vai casar com uma sessão real do ~/.claude/projects/.
"""

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from .claude_sessions import project_sessions_dir
from .storage import config_dir

log = logging.getLogger(__name__)


def session_state_file() -> Path:
    return config_dir() / "session_state.json"


@dataclass
class SavedSession:
    workspace_id: str
    session_id: str
    cwd: str
    backend: str = "claude"  # "claude" ou "opencode"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SavedSession":
        session_id = str(data.get("session_id") or "")
        backend = str(data.get("backend") or "claude")
        # Migração/defesa: sessões OpenCode usam IDs `ses_...`. Durante a
        # primeira versão multi-backend alguns terminais podiam ser salvos
        # como Claude e depois restaurados com `opencode -s <uuid>` ou o
        # inverso, quebrando o startup.
        if session_id.startswith("ses_"):
            backend = "opencode"
        return cls(
            workspace_id=str(data.get("workspace_id") or ""),
            session_id=session_id,
            cwd=str(data.get("cwd") or ""),
            backend=backend,
        )

    def is_valid(self) -> bool:
        return bool(self.workspace_id and self.session_id and self.cwd)

    def session_file(self) -> Path:
        if self.backend == "opencode":
            return Path(self.cwd)  # opencode não tem JSONL por sessão
        return project_sessions_dir(self.cwd) / f"{self.session_id}.jsonl"


def load_saved_sessions() -> list[SavedSession]:
    path = session_state_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.warning("Não consegui ler %s", path)
        return []
    raw = data.get("sessions", [])
    if not isinstance(raw, list):
        return []
    result: list[SavedSession] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        s = SavedSession.from_dict(item)
        if s.is_valid():
            result.append(s)
    return result


def save_sessions(sessions: list[SavedSession]) -> None:
    path = session_state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"sessions": [s.to_dict() for s in sessions if s.is_valid()]}
    try:
        if path.exists():
            backup = path.with_suffix(".json.bak")
            backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        log.exception("Falha ao salvar session state em %s", path)


def clear_saved_sessions() -> None:
    path = session_state_file()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        log.debug("Falha ao remover %s", path, exc_info=True)


# ---- sessões de workspaces minimizados ------------------------------------
# Ao minimizar um workspace, seus consoles são encerrados (libera RAM do
# claude + MCP). As sessões resumíveis ficam guardadas por workspace_id pra
# recriar via --resume quando o workspace volta. Persistido à parte do
# session_state pra sobreviver a um restart com o workspace ainda minimizado.


def minimized_sessions_file() -> Path:
    return config_dir() / "minimized_sessions.json"


def load_minimized_sessions() -> dict[str, list[SavedSession]]:
    path = minimized_sessions_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.warning("Não consegui ler %s", path)
        return {}
    raw = data.get("workspaces", {})
    if not isinstance(raw, dict):
        return {}
    result: dict[str, list[SavedSession]] = {}
    for ws_id, items in raw.items():
        if not isinstance(items, list):
            continue
        sessions = [
            SavedSession.from_dict(it) for it in items if isinstance(it, dict)
        ]
        sessions = [s for s in sessions if s.is_valid()]
        if sessions:
            result[str(ws_id)] = sessions
    return result


def save_minimized_sessions(mapping: dict[str, list[SavedSession]]) -> None:
    path = minimized_sessions_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "workspaces": {
            ws_id: [s.to_dict() for s in sessions if s.is_valid()]
            for ws_id, sessions in mapping.items()
            if sessions
        }
    }
    try:
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        log.exception("Falha ao salvar minimized sessions em %s", path)
