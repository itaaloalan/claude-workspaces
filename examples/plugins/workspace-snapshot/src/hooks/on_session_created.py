"""session.created — incrementa o contador da janela atual do workspace."""

from claude_workspaces.plugin_api import HookContext, SessionCreatedPayload


async def handler(ctx: HookContext, payload: SessionCreatedPayload) -> None:
    key = f"ws:{payload.workspace_id}:current"
    snap = await ctx.storage.get(key)
    if not isinstance(snap, dict):
        return
    snap["sessions_created"] = int(snap.get("sessions_created", 0)) + 1
    await ctx.storage.set(key, snap)
