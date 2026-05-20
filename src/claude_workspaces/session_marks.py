"""Persiste marcações por sessão (favoritar / tags / notas).

Não dá pra mexer em `~/.claude/projects/` (território do Claude Code),
então mantemos um arquivo próprio em `config_dir()/session_marks.json`
indexado por session_id.

Estrutura por entrada — apenas `starred` é usado hoje, `tags` e `note`
ficam reservados pra evolução futura sem precisar migrar formato:

    {
      "<session_id>": {
        "starred": true,
        "tags": ["foo", "bar"],
        "note": "",
        "cwd": "/caminho/do/projeto"
      }
    }
"""

import json
import logging
from pathlib import Path

from .storage import config_dir

log = logging.getLogger(__name__)


def _marks_file() -> Path:
    return config_dir() / "session_marks.json"


def load_marks() -> dict[str, dict]:
    path = _marks_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.warning("Não consegui ler %s", path)
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict] = {}
    for sid, entry in data.items():
        if isinstance(sid, str) and isinstance(entry, dict):
            out[sid] = entry
    return out


def _save_marks(marks: dict[str, dict]) -> None:
    path = _marks_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(marks, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def is_starred(session_id: str) -> bool:
    return bool(load_marks().get(session_id, {}).get("starred"))


def starred_ids() -> set[str]:
    return {
        sid for sid, entry in load_marks().items() if entry.get("starred")
    }


def set_starred(session_id: str, starred: bool, cwd: str = "") -> None:
    marks = load_marks()
    entry = marks.get(session_id, {})
    if starred:
        entry["starred"] = True
        if cwd:
            entry["cwd"] = cwd
        marks[session_id] = entry
    else:
        if not entry:
            return
        entry.pop("starred", None)
        if not entry.get("tags") and not entry.get("note") and not entry.get("custom_name"):
            marks.pop(session_id, None)
        else:
            marks[session_id] = entry
    _save_marks(marks)


def get_custom_name(session_id: str) -> str:
    """Nome custom escolhido pelo usuário pra essa sessão. Vazio = sem
    rename. Usado pelo TerminalWidget pra montar `effective_title()` e
    pelas notificações (toast / native) pra mostrar o nome que o usuário
    deu, em vez do preview do primeiro user prompt."""
    if not session_id:
        return ""
    name = load_marks().get(session_id, {}).get("custom_name", "")
    return name if isinstance(name, str) else ""


def set_custom_name(session_id: str, name: str, cwd: str = "") -> None:
    """Salva (ou apaga, se `name` vazio) o nome custom da sessão."""
    if not session_id:
        return
    marks = load_marks()
    entry = marks.get(session_id, {})
    name = (name or "").strip()
    if name:
        entry["custom_name"] = name
        if cwd:
            entry["cwd"] = cwd
        marks[session_id] = entry
    else:
        if not entry:
            return
        entry.pop("custom_name", None)
        if (
            not entry.get("starred")
            and not entry.get("tags")
            and not entry.get("note")
        ):
            marks.pop(session_id, None)
        else:
            marks[session_id] = entry
    _save_marks(marks)
