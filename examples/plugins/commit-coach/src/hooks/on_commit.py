"""Avalia mensagens de commit recém-criadas.

Sem acesso a filesystem ou rede: trabalhamos apenas com o payload do evento
(sha + mensagem). O feedback chega via toast para não roubar o foco —
notificações pesadas ficam reservadas pra coisas urgentes."""

import re

from claude_workspaces.plugin_api import CommitCreatedPayload, HookContext

# Tipos canônicos de Conventional Commits + alguns que aparecem no repo.
_CONVENTIONAL_TYPES = (
    "feat",
    "fix",
    "docs",
    "style",
    "refactor",
    "perf",
    "test",
    "build",
    "ci",
    "chore",
    "revert",
    "merge",
)
_CONVENTIONAL_RE = re.compile(
    r"^(?P<type>[a-z]+)(\([^)]+\))?!?:\s+(?P<subject>.+)$"
)
_WIP_HINTS = re.compile(r"\b(wip|tmp|temp|fix\s*me|fixme|todo|xxx)\b", re.IGNORECASE)


async def handler(ctx: HookContext, payload: CommitCreatedPayload) -> None:
    msg = payload.message or ""
    subject = msg.splitlines()[0] if msg else ""
    sha_short = (payload.sha or "")[:7]

    enforce = await ctx.config.get("enforce_conventional")
    max_len = await ctx.config.get("max_subject_length")
    warn_wip = await ctx.config.get("warn_on_wip")

    problems: list[str] = []

    if enforce:
        match = _CONVENTIONAL_RE.match(subject)
        if not match:
            problems.append(
                "não segue Conventional Commits (ex: feat: ..., fix(escopo): ...)"
            )
        else:
            t = match.group("type")
            if t not in _CONVENTIONAL_TYPES:
                problems.append(
                    f"tipo {t!r} fora da lista canônica "
                    f"({', '.join(_CONVENTIONAL_TYPES)})"
                )

    if isinstance(max_len, int) and len(subject) > max_len:
        problems.append(
            f"assunto com {len(subject)} caracteres (limite {max_len})"
        )

    if warn_wip and _WIP_HINTS.search(subject):
        problems.append("o assunto parece WIP — confirme se é commit final")

    if not problems:
        ctx.log.info("commit ok", sha=sha_short)
        return

    body = "; ".join(problems)
    ctx.log.warn("commit com sinais de problema", sha=sha_short, problems=problems)
    await ctx.ui.toast(
        message=f"commit {sha_short}: {body}",
        level="warning",
    )
