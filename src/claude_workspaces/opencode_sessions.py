import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


OPCODE_DB_PATH = Path.home() / ".local" / "share" / "opencode" / "opencode.db"


@dataclass
class OpencodeSession:
    id: str
    mtime: float
    preview: str
    path: str
    origin_cwd: str
    directory: str
    title: str
    slug: str
    agent: str = ""
    model: str = ""

    def label(self, max_preview: int = 70, include_origin: bool = False) -> str:
        dt = datetime.fromtimestamp(self.mtime)
        now = datetime.now()
        if dt.date() == now.date():
            time_str = "hoje " + dt.strftime("%H:%M")
        elif (now.date() - dt.date()).days == 1:
            time_str = "ontem " + dt.strftime("%H:%M")
        else:
            time_str = dt.strftime("%d/%m %H:%M")

        prefix = ""
        if include_origin:
            prefix = f"[{Path(self.origin_cwd).name}] "

        preview = (self.preview or self.title or "").replace("\n", " ").strip()
        if len(preview) > max_preview:
            preview = preview[: max_preview - 1] + "…"
        if preview:
            return f"{prefix}{time_str} — {preview}"
        return f"{prefix}{time_str} — (sem título)"


def _opencode_db() -> Path:
    return OPCODE_DB_PATH


def _read_first_user_message(session_id: str) -> str:
    """Lê a primeira mensagem textual do usuário de uma sessão opencode via DB."""
    db_path = _opencode_db()
    if not db_path.exists():
        return ""
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """SELECT m.data AS message_data, p.data AS part_data
               FROM message m
               JOIN part p ON p.message_id = m.id
               WHERE m.session_id = ?
               ORDER BY m.time_created ASC, p.time_created ASC""",
            (session_id,),
        )
        for row in cursor.fetchall():
            message_data = json.loads(row["message_data"])
            if message_data.get("role") != "user":
                continue
            part_data = json.loads(row["part_data"])
            if part_data.get("type") != "text":
                continue
            text = (part_data.get("text") or "").strip()
            if text:
                return text
        return ""
    except (sqlite3.Error, json.JSONDecodeError, OSError) as e:
        log.warning("Falha ao ler primeira mensagem da sessão %s: %s", session_id, e)
        return ""
    finally:
        if conn is not None:
            conn.close()


def list_sessions(project_path: str, limit: int = 15) -> list[OpencodeSession]:
    """Lista sessões opencode de um diretório específico."""
    db_path = _opencode_db()
    if not db_path.exists():
        return []
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, slug, directory, title, time_created, time_updated,
                      agent, model, tokens_input, tokens_output
               FROM session
               WHERE directory = ?
               ORDER BY time_updated DESC
               LIMIT ?""",
            (project_path, limit),
        )
        rows = cursor.fetchall()
    except (sqlite3.Error, OSError) as e:
        log.warning("Falha ao listar sessões opencode em %s: %s", project_path, e)
        return []
    finally:
        if conn is not None:
            conn.close()

    sessions: list[OpencodeSession] = []
    for row in rows:
        # Parse model from JSON if needed
        model_raw = row["model"]
        model = ""
        if model_raw:
            try:
                m = json.loads(model_raw)
                model = m.get("id", "")
            except (json.JSONDecodeError, TypeError):
                model = str(model_raw)

        preview = _read_first_user_message(row["id"])

        sessions.append(
            OpencodeSession(
                id=row["id"],
                mtime=row["time_updated"] / 1000,
                preview=preview,
                path=str(db_path),
                origin_cwd=row["directory"],
                directory=row["directory"],
                title=row["title"],
                slug=row["slug"],
                agent=row["agent"] or "",
                model=model,
            )
        )
    return sessions


def list_sessions_for_paths(paths: list[str], limit: int = 20) -> list[OpencodeSession]:
    """Agrega sessões de múltiplos caminhos."""
    from .session_marks import starred_ids

    seen_dirs: set[str] = set()
    all_sessions: list[OpencodeSession] = []
    for p in paths:
        norm = str(Path(p).resolve())
        if norm in seen_dirs:
            continue
        seen_dirs.add(norm)
        all_sessions.extend(list_sessions(norm, limit=limit))

    all_sessions.sort(key=lambda s: s.mtime, reverse=True)
    top = all_sessions[:limit]

    starred = starred_ids()
    if starred:
        present_ids = {s.id for s in top}
        for sid in starred - present_ids:
            for p in paths:
                s_list = list_sessions(p, limit=200)
                for s in s_list:
                    if s.id == sid and sid not in present_ids:
                        top.append(s)
                        present_ids.add(sid)
                        break
        top.sort(key=lambda s: s.mtime, reverse=True)
    return top
