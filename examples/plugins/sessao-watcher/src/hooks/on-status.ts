import { HookContext, SessionStatusChangedPayload } from "@claude-workspaces/api";

export default async function (
  ctx: HookContext,
  payload: SessionStatusChangedPayload
): Promise<void> {
  if (payload.newStatus !== "awaiting-input") return;

  const thresholdMin = await ctx.config.get<number>("threshold_minutes");
  if (payload.durationMs < thresholdMin * 60 * 1000) return;

  const session = await ctx.sessions.get(payload.sessionId);
  await ctx.ui.notify({
    title: "Sessão aguardando há muito tempo",
    body: `${session.workspaceName}: ${session.lastMessage ?? "(sem título)"}`,
    actions: [{ id: "focus", label: "Abrir" }],
  });
}
