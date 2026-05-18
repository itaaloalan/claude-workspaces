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
    origin_cwd: str  # diretório de onde a sessão foi originalmente iniciada

    def label(self, max_preview: int = 70, include_origin: bool = False) -> str:
        when = datetime.fromtimestamp(self.mtime)
        now = datetime.now()
        if when.date() == now.date():
            time_str = "hoje " + when.strftime("%H:%M")
        elif (now.date() - when.date()).days == 1:
            time_str = "ontem " + when.strftime("%H:%M")
        else:
            time_str = when.strftime("%d/%m %H:%M")

        prefix = ""
        if include_origin:
            prefix = f"[{Path(self.origin_cwd).name}] "

        if self.preview:
            preview = self.preview.replace("\n", " ").strip()
            if len(preview) > max_preview:
                preview = preview[: max_preview - 1] + "…"
            return f"{prefix}{time_str} — {preview}"
        return f"{prefix}{time_str} — (sem prompt registrado)"


def _encode_project_path(path: str) -> str:
    """Claude Code armazena cada projeto em ~/.claude/projects/<path-com-/-trocada-por-->"""
    return path.replace("/", "-")


def project_sessions_dir(project_path: str) -> Path:
    return Path.home() / ".claude" / "projects" / _encode_project_path(project_path)


def _extract_text(content) -> str:
    """Normaliza o campo `content` (str ou lista de blocos) pra um texto único.
    Pula blocos não-textuais (tool_use, tool_result, image)."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                t = (c.get("text") or "").strip()
                if t:
                    parts.append(t)
        return "\n".join(parts).strip()
    return ""


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
                text = _extract_text(inner.get("content"))
                if text:
                    return text
    except OSError:
        log.warning("Não consegui ler arquivo de sessão %s", jsonl_path)
    return ""


def read_recent_turns(
    jsonl_path: Path, max_total: int = 6
) -> list[tuple[str, str]]:
    """Lê os últimos N turnos do JSONL (user + assistant, só com texto).
    Devolve em ordem cronológica (mais antigo → mais recente).
    Pula tool_use/tool_result/imagens."""
    all_turns: list[tuple[str, str]] = []
    try:
        with jsonl_path.open(encoding="utf-8") as fp:
            for line in fp:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg_type = msg.get("type")
                if msg_type not in ("user", "assistant"):
                    continue
                inner = msg.get("message")
                if not isinstance(inner, dict):
                    continue
                text = _extract_text(inner.get("content"))
                if not text:
                    continue
                all_turns.append((msg_type, text))
    except OSError:
        log.warning("Não consegui ler arquivo de sessão %s", jsonl_path)
        return []
    return all_turns[-max_total:]


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
                origin_cwd=project_path,
            )
        )
    return sessions


def list_sessions_for_paths(paths: list[str], limit: int = 20) -> list[ClaudeSession]:
    """Agrega sessões de múltiplos caminhos (cwd potenciais) e devolve
    ordenado por mtime descendente. Cada sessão preserva o origin_cwd
    pra que retomá-la use o cwd correto onde foi originalmente iniciada
    (importante quando workspace tem pastas-irmãs e o VSCode plugin
    abriu sessões em uma das subpastas específicas).

    Sessões favoritadas (★) que pertençam a algum dos `paths` são sempre
    incluídas, mesmo que estejam fora do `limit` mais recente — é o que
    permite "fechar e achar depois" pelo filtro de favoritas."""
    # Import local pra evitar ciclo (session_marks → storage → models)
    from .session_marks import starred_ids

    seen_dirs: set[Path] = set()
    all_sessions: list[ClaudeSession] = []
    for p in paths:
        d = project_sessions_dir(p)
        if d in seen_dirs:
            continue
        seen_dirs.add(d)
        all_sessions.extend(list_sessions(p, limit=limit))
    all_sessions.sort(key=lambda s: s.mtime, reverse=True)
    top = all_sessions[:limit]

    # Acrescenta favoritas que ficaram de fora do top-N
    starred = starred_ids()
    if starred:
        present_ids = {s.id for s in top}
        for sid in starred - present_ids:
            for p in paths:
                f = project_sessions_dir(p) / f"{sid}.jsonl"
                if not f.is_file():
                    continue
                try:
                    mtime = f.stat().st_mtime
                except OSError:
                    break
                top.append(
                    ClaudeSession(
                        id=sid,
                        mtime=mtime,
                        preview=_read_first_user_message(f),
                        path=f,
                        origin_cwd=p,
                    )
                )
                break
        top.sort(key=lambda s: s.mtime, reverse=True)
    return top
