"""commit.created — incrementa o contador de commits da janela atual."""

from claude_workspaces.plugin_api import CommitCreatedPayload, HookContext


async def handler(ctx: HookContext, payload: CommitCreatedPayload) -> None:
    key = f"ws:{payload.workspace_id}:current"
    snap = await ctx.storage.get(key)
    if not isinstance(snap, dict):
        return
    snap["commits_created"] = int(snap.get("commits_created", 0)) + 1
    await ctx.storage.set(key, snap)
