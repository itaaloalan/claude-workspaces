import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


log = logging.getLogger(__name__)


@dataclass
class ClaudeSession:
    id: str
    mtime: float
    preview: str
    path: Path

    def label(self, max_preview: int = 70) -> str:
        when = datetime.fromtimestamp(self.mtime)
        now = datetime.now()
        if when.date() == now.date():
            time_str = "hoje " + when.strftime("%H:%M")
        elif (now.date() - when.date()).days == 1:
            time_str = "ontem " + when.strftime("%H:%M")
        else:
            time_str = when.strftime("%d/%m %H:%M")

        if self.preview:
            preview = self.preview.replace("\n", " ").strip()
            if len(preview) > max_preview:
                preview = preview[: max_preview - 1] + "…"
            return f"{time_str} — {preview}"
        return f"{time_str} — (sem prompt registrado)"


def _encode_project_path(path: str) -> str:
    """Claude Code armazena cada projeto em ~/.claude/projects/<path-com-/-trocada-por-->"""
    return path.replace("/", "-")


def project_sessions_dir(project_path: str) -> Path:
    return Path.home() / ".claude" / "projects" / _encode_project_path(project_path)


def _read_first_user_message(jsonl_path: Path) -> str:
    """Lê a primeira mensagem do usuário (texto) num arquivo .jsonl de sessão."""
    try:
        with jsonl_path.open(encoding="utf-8") as fp:
            for line in fp:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") != "user":
                    continue
                inner = msg.get("message")
                if not isinstance(inner, dict):
                    continue
                content = inner.get("content")
                if isinstance(content, str):
                    text = content.strip()
                    if text:
                        return text
                elif isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            text = (c.get("text") or "").strip()
                            if text:
                                return text
    except OSError:
        log.warning("Não consegui ler arquivo de sessão %s", jsonl_path)
    return ""


def list_sessions(project_path: str, limit: int = 15) -> list[ClaudeSession]:
    d = project_sessions_dir(project_path)
    if not d.is_dir():
        return []
    try:
        files = sorted(
            d.glob("*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        log.warning("Falha ao listar %s", d)
        return []

    sessions: list[ClaudeSession] = []
    for f in files[:limit]:
        try:
            mtime = f.stat().st_mtime
        except OSError:
            continue
        sessions.append(
            ClaudeSession(
                id=f.stem,
                mtime=mtime,
                preview=_read_first_user_message(f),
                path=f,
            )
        )
    return sessions
