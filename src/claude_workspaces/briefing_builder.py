"""Monta um briefing enriquecido pra handoff: contexto da sessão anterior +
estado do repo (branch, arquivos modificados), formatado pra colar como
primeira mensagem de um novo Claude.

Mantido puro (sem PySide) pra ser fácil de testar."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from .claude_sessions import ClaudeSession, read_recent_turns

log = logging.getLogger(__name__)

MAX_TURN_CHARS = 600
MAX_FILES_LISTED = 20
MAX_TURNS = 6


@dataclass
class BriefingContext:
    branch: str = ""
    ahead: int = 0
    behind: int = 0
    changed_files: list[tuple[str, str]] = field(default_factory=list)
    recent_turns: list[tuple[str, str]] = field(default_factory=list)


def collect_context(
    session: ClaudeSession, primary_folder: str
) -> BriefingContext:
    """Junta tudo que entra no briefing. Tolera falhas — cada fonte vira
    opcional (seção some se não tem dado)."""
    ctx = BriefingContext()
    if session.path:
        try:
            ctx.recent_turns = read_recent_turns(session.path, max_total=MAX_TURNS)
        except Exception:
            log.exception("Falha lendo turnos da sessão %s", session.path)
    if primary_folder:
        # Import local pra não pagar subprocess.import em quem só usa render
        try:
            from .git_status import get_status

            st = get_status(primary_folder)
        except Exception:
            log.exception("Falha lendo git status em %s", primary_folder)
            st = None
        if st and st.is_repo:
            ctx.branch = st.branch
            ctx.ahead = st.ahead
            ctx.behind = st.behind
            ctx.changed_files = [
                (f.label(), f.path) for f in st.files[:MAX_FILES_LISTED]
            ]
    return ctx


def _truncate(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def render_briefing(session: ClaudeSession, ctx: BriefingContext) -> str:
    """Formata o briefing como texto colável. Sempre termina com
    'Próximo passo: ' pra o cursor cair ali."""
    short_id = session.id[:8] if session.id else "?"
    origin_name = Path(session.origin_cwd).name if session.origin_cwd else "?"
    parts: list[str] = [
        f"Continuando trabalho da sessão #{short_id} ({origin_name})."
    ]

    if ctx.branch:
        ab = ""
        if ctx.ahead or ctx.behind:
            ab = f" (↑{ctx.ahead} ↓{ctx.behind})"
        parts.append(f"\nBranch atual: `{ctx.branch}`{ab}.")

    if ctx.changed_files:
        parts.append("\nArquivos com mudanças:")
        for label, path in ctx.changed_files:
            parts.append(f"  - {label}: {path}")
        if len(ctx.changed_files) >= MAX_FILES_LISTED:
            parts.append(f"  (truncado em {MAX_FILES_LISTED} arquivos)")

    if ctx.recent_turns:
        parts.append("\nÚltimos turnos da sessão:")
        for role, text in ctx.recent_turns:
            label = "Você" if role == "user" else "Claude"
            parts.append(f"\n[{label}]")
            parts.append(_truncate(text, MAX_TURN_CHARS))
    else:
        preview = (session.preview or "").strip()
        if preview:
            parts.append("\nTarefa original:")
            parts.append(f"> {_truncate(preview, MAX_TURN_CHARS)}")

    parts.append("\n\nPróximo passo: ")
    return "\n".join(parts)


def build_briefing(session: ClaudeSession, primary_folder: str = "") -> str:
    """Atalho: collect_context + render_briefing."""
    return render_briefing(session, collect_context(session, primary_folder))
