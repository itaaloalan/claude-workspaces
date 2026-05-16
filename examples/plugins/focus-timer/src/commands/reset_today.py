"""Comando: zera as contagens do dia."""

from datetime import datetime, timezone

from claude_workspaces.plugin_api import CommandContext


async def handler(ctx: CommandContext) -> None:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prefix = f"day:{day}"

    keys = (
        f"{prefix}:running_ms",
        f"{prefix}:awaiting-input_ms",
        f"{prefix}:idle_ms",
        f"{prefix}:completed_count",
        f"{prefix}:completed_total_ms",
    )
    for k in keys:
        await ctx.storage.delete(k)

    ctx.log.info("contadores zerados", day=day)
    await ctx.ui.toast(message=f"Focus: contadores de {day} zerados.", level="info")
