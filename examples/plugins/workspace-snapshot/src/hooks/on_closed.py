"""workspace.closed — calcula resumo e notifica se passou do mínimo configurado.

Lê o snapshot atual, descarta-o e tenta buscar o nome do workspace pra
montar um resumo legível. Se o workspace já tiver sido removido, cai num
fallback com o ID."""

import time

from claude_workspaces.plugin_api import HookContext, WorkspaceClosedPayload


def _fmt_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    secs = seconds % 60
    if minutes < 60:
        return f"{minutes}min{secs:02d}s" if secs else f"{minutes}min"
    hours = minutes // 60
    minutes_in_hour = minutes % 60
    if minutes_in_hour:
        return f"{hours}h{minutes_in_hour:02d}min"
    return f"{hours}h"


async def _resolve_name(ctx, workspace_id: str) -> str:
    try:
        ws = await ctx.workspaces.get(workspace_id)
        if ws and getattr(ws, "name", ""):
            return ws.name
    except Exception:  # noqa: BLE001 — workspace pode ter sumido
        pass
    return workspace_id


async def handler(ctx: HookContext, payload: WorkspaceClosedPayload) -> None:
    key = f"ws:{payload.workspace_id}:current"
    snap = await ctx.storage.get(key)
    if not isinstance(snap, dict):
        ctx.log.info("workspace fechado sem snapshot", workspace_id=payload.workspace_id)
        return

    opened_at_ms = int(snap.get("opened_at_ms", 0))
    sessions = int(snap.get("sessions_created", 0))
    commits = int(snap.get("commits_created", 0))
    duration_ms = max(0, int(time.time() * 1000) - opened_at_ms) if opened_at_ms else 0
    duration_s = duration_ms // 1000

    await ctx.storage.delete(key)

    min_seconds = await ctx.config.get("min_duration_seconds")
    if not isinstance(min_seconds, int):
        min_seconds = 30
    notify = await ctx.config.get("notify_on_close")

    ctx.log.info(
        "workspace fechado",
        workspace_id=payload.workspace_id,
        duration_s=duration_s,
        sessions=sessions,
        commits=commits,
    )

    if not notify or duration_s < min_seconds:
        return

    name = await _resolve_name(ctx, payload.workspace_id)

    body_parts = [f"Duração: {_fmt_duration(duration_s)}"]
    if sessions:
        body_parts.append(f"Sessões abertas: {sessions}")
    if commits:
        body_parts.append(f"Commits: {commits}")
    if not sessions and not commits:
        body_parts.append("Sem sessões nem commits durante a janela.")

    await ctx.ui.notify(
        title=f"Snapshot — {name}",
        body="\n".join(body_parts),
    )
