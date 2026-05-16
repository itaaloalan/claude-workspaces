"""Detecta sessões paradas em awaiting-input por muito tempo.

Diferente do `sessao-watcher`, que só sinaliza, aqui montamos um *nudge*:
uma mensagem curta com sugestão de prompt pra retomar do ponto onde a
sessão parou. O tom é configurável (gentil/direto/técnico)."""

from claude_workspaces.plugin_api import HookContext, SessionStatusChangedPayload

_NUDGE_PREFIX = {
    "gentil": "Bora retomar?",
    "direto": "Sessão parada.",
    "tecnico": "Sessão IDLE (awaiting-input).",
}

_NUDGE_SUGGESTION = {
    "gentil": "Tente: \"continua daí com calma, e me avisa se precisar de contexto\"",
    "direto": "Sugestão: \"continue\" ou \"finalize o que faltou\"",
    "tecnico": "Sugestão: enviar `/resume` ou prompt com checkpoint do estado",
}


def _truncate(text: str, limit: int = 80) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


async def handler(
    ctx: HookContext, payload: SessionStatusChangedPayload
) -> None:
    if payload.new_status != "awaiting-input":
        return

    threshold_min = await ctx.config.get("idle_threshold_minutes")
    if not isinstance(threshold_min, int) or threshold_min <= 0:
        threshold_min = 10
    if payload.duration_ms < threshold_min * 60 * 1000:
        return

    style = await ctx.config.get("nudge_style")
    if style not in _NUDGE_PREFIX:
        style = "gentil"
    include_last = await ctx.config.get("include_last_message")

    session = await ctx.sessions.get(payload.session_id)
    prefix = _NUDGE_PREFIX[style]
    suggestion = _NUDGE_SUGGESTION[style]
    workspace = session.workspace_name or "workspace"

    body_parts = [f"[{workspace}]"]
    if include_last and session.last_message:
        body_parts.append(f"Último: {_truncate(session.last_message)}")
    body_parts.append(suggestion)

    ctx.log.info(
        "nudge enviado",
        session_id=payload.session_id,
        idle_minutes=payload.duration_ms // 60_000,
        style=style,
    )
    await ctx.ui.notify(
        title=prefix,
        body="\n".join(body_parts),
    )
