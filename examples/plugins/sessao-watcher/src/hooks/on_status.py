from claude_workspaces.plugin_api import HookContext, SessionStatusChangedPayload


async def handler(
    ctx: HookContext, payload: SessionStatusChangedPayload
) -> None:
    if payload.new_status != "awaiting-input":
        return

    threshold_min = await ctx.config.get("threshold_minutes")
    if payload.duration_ms < threshold_min * 60 * 1000:
        return

    session = await ctx.sessions.get(payload.session_id)
    await ctx.ui.notify(
        title="Sessão aguardando há muito tempo",
        body=f"{session.workspace_name}: {session.last_message or '(sem título)'}",
    )
