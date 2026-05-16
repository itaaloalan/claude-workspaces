"""Comando: mostra resumo das contagens do dia via notificação."""

from datetime import datetime, timezone

from claude_workspaces.plugin_api import CommandContext


def _fmt_duration(ms: int) -> str:
    if ms <= 0:
        return "0min"
    total_minutes = ms // 60_000
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if hours and minutes:
        return f"{hours}h{minutes:02d}min"
    if hours:
        return f"{hours}h"
    return f"{minutes}min"


async def handler(ctx: CommandContext) -> None:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prefix = f"day:{day}"

    running = await ctx.storage.get(f"{prefix}:running_ms") or 0
    awaiting = await ctx.storage.get(f"{prefix}:awaiting-input_ms") or 0
    idle = await ctx.storage.get(f"{prefix}:idle_ms") or 0
    completed = await ctx.storage.get(f"{prefix}:completed_count") or 0

    body = (
        f"Running: {_fmt_duration(running)}\n"
        f"Aguardando: {_fmt_duration(awaiting)}\n"
        f"Idle: {_fmt_duration(idle)}\n"
        f"Sessões concluídas: {completed}"
    )

    await ctx.ui.notify(title=f"Focus — {day}", body=body)
    ctx.log.info(
        "resumo solicitado",
        day=day,
        running_ms=running,
        awaiting_ms=awaiting,
        idle_ms=idle,
        completed=completed,
    )
