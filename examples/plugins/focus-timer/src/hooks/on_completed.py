"""Conta sessões concluídas e soma duração total no dia."""

from datetime import datetime, timezone

from claude_workspaces.plugin_api import HookContext, SessionCompletedPayload


def _today_prefix() -> str:
    return "day:" + datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def handler(ctx: HookContext, payload: SessionCompletedPayload) -> None:
    prefix = _today_prefix()
    count_key = f"{prefix}:completed_count"
    duration_key = f"{prefix}:completed_total_ms"

    count = await ctx.storage.get(count_key)
    total = await ctx.storage.get(duration_key)
    if not isinstance(count, int):
        count = 0
    if not isinstance(total, int):
        total = 0

    await ctx.storage.set(count_key, count + 1)
    await ctx.storage.set(duration_key, total + max(0, payload.duration_ms))

    ctx.log.info(
        "sessão concluída",
        reason=payload.reason,
        duration_ms=payload.duration_ms,
        completed_today=count + 1,
    )
