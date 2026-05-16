"""Acumula tempo gasto em cada status no totalizador do dia.

Quando uma sessão transita de status, o payload traz `oldStatus` e
`durationMs` (quanto tempo ficou no status anterior). Isso vai pro bucket
do dia em `ctx.storage`, indexado por data UTC."""

from datetime import datetime, timezone

from claude_workspaces.plugin_api import HookContext, SessionStatusChangedPayload


def _today_key(status: str) -> str:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"day:{day}:{status}_ms"


_TRACKED_STATUSES = ("running", "awaiting-input", "idle")


async def handler(
    ctx: HookContext, payload: SessionStatusChangedPayload
) -> None:
    if payload.old_status not in _TRACKED_STATUSES:
        return
    if payload.duration_ms <= 0:
        return

    count_idle = await ctx.config.get("count_idle_as_focus")
    if payload.old_status == "idle" and not count_idle:
        return

    key = _today_key(payload.old_status)
    current = await ctx.storage.get(key)
    if not isinstance(current, int):
        current = 0
    await ctx.storage.set(key, current + payload.duration_ms)

    ctx.log.info(
        "tempo acumulado",
        status=payload.old_status,
        added_ms=payload.duration_ms,
        total_ms=current + payload.duration_ms,
    )
