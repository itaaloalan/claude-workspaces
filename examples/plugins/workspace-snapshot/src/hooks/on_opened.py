"""workspace.opened — guarda timestamp de abertura e zera contadores da janela atual."""

import time

from claude_workspaces.plugin_api import HookContext, WorkspaceOpenedPayload


async def handler(ctx: HookContext, payload: WorkspaceOpenedPayload) -> None:
    ws_id = payload.workspace_id
    snapshot = {
        "opened_at_ms": int(time.time() * 1000),
        "sessions_created": 0,
        "commits_created": 0,
    }
    await ctx.storage.set(f"ws:{ws_id}:current", snapshot)
    ctx.log.info("workspace aberto", workspace_id=ws_id)
