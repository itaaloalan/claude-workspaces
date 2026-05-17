"""Busca de texto livre através de todas as sessões do Claude Code.

Não é semântica de verdade (sem embeddings) — é substring + acertos
por timestamp, mas resolve 90% do caso "onde eu trabalhei em X mês passado".

Itera ~/.claude/projects/*/*.jsonl, concatena texto user+assistant, faz
search com snippet de contexto e retorna ordenado por recência.
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

SNIPPET_RADIUS = 80  # chars antes/depois do match
MAX_HITS = 100


@dataclass
class SearchHit:
    session_id: str
    project_path: str   # cwd onde a sessão rodou
    file_path: Path     # caminho do .jsonl
    last_modified: datetime
    match_count: int
    snippet: str
    first_prompt: str

    def label(self) -> str:
        preview = self.first_prompt.replace("\n", " ").strip()
        if len(preview) > 70:
            preview = preview[:69] + "…"
        return preview or "(sem prompt)"


def _project_path_from_encoded(name: str) -> str:
    """Reverte o nome do diretório de projeto pra path absoluto.
    Claude codifica '/' como '-', então /home/user/foo vira -home-user-foo."""
    if name.startswith("-"):
        return "/" + name[1:].replace("-", "/")
    return name


def _read_session_text(path: Path) -> tuple[str, str]:
    """Devolve (texto_concatenado, primeiro_user_prompt)."""
    parts: list[str] = []
    first_prompt = ""
    try:
        with path.open(encoding="utf-8") as fp:
            for line in fp:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg_type = msg.get("type")
                inner = msg.get("message")
                if not isinstance(inner, dict):
                    continue
                content = inner.get("content")
                if isinstance(content, str):
                    parts.append(content)
                    if msg_type == "user" and not first_prompt:
                        first_prompt = content
                elif isinstance(content, list):
                    for c in content:
                        if not isinstance(c, dict):
                            continue
                        if c.get("type") == "text":
                            t = c.get("text") or ""
                            parts.append(t)
                            if msg_type == "user" and not first_prompt:
                                first_prompt = t
    except OSError as e:
        log.debug("Skip %s: %s", path, e)
    return "\n".join(parts), first_prompt


def _make_snippet(text: str, needle: str) -> str:
    if not needle:
        return ""
    idx = text.lower().find(needle.lower())
    if idx < 0:
        return ""
    start = max(0, idx - SNIPPET_RADIUS)
    end = min(len(text), idx + len(needle) + SNIPPET_RADIUS)
    snippet = text[start:end].replace("\n", " ").strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


def search_sessions(
    query: str,
    since: datetime | None = None,
) -> list[SearchHit]:
    """Busca substring em todas as sessões. since (UTC) limita por data
    de modificação do arquivo."""
    needle = (query or "").strip()
    if not needle:
        return []
    needle_lower = needle.lower()
    base = Path.home() / ".claude" / "projects"
    if not base.is_dir():
        return []
    hits: list[SearchHit] = []
    try:
        projects = list(base.iterdir())
    except OSError:
        return []
    for proj in projects:
        if not proj.is_dir():
            continue
        project_path = _project_path_from_encoded(proj.name)
        for jsonl in proj.glob("*.jsonl"):
            try:
                mtime_ts = jsonl.stat().st_mtime
            except OSError:
                continue
            last_modified = datetime.fromtimestamp(mtime_ts, tz=UTC)
            if since and last_modified < since:
                continue
            text, first_prompt = _read_session_text(jsonl)
            if not text:
                continue
            count = text.lower().count(needle_lower)
            if count <= 0:
                continue
            snippet = _make_snippet(text, needle)
            hits.append(
                SearchHit(
                    session_id=jsonl.stem,
                    project_path=project_path,
                    file_path=jsonl,
                    last_modified=last_modified,
                    match_count=count,
                    snippet=snippet,
                    first_prompt=first_prompt,
                )
            )
    hits.sort(key=lambda h: h.last_modified, reverse=True)
    return hits[:MAX_HITS]
