import handler from "../src/hooks/on-status";

describe("on-status", () => {
  it("ignora status diferente de awaiting-input", async () => {
    const ctx = makeCtx({ thresholdMin: 5 });
    await handler(ctx as any, {
      sessionId: "s1",
      oldStatus: "running",
      newStatus: "idle",
      durationMs: 9999999,
    } as any);
    expect(ctx.ui.notify).not.toHaveBeenCalled();
  });

  it("não notifica antes do threshold", async () => {
    const ctx = makeCtx({ thresholdMin: 5 });
    await handler(ctx as any, {
      sessionId: "s1",
      oldStatus: "running",
      newStatus: "awaiting-input",
      durationMs: 60 * 1000,
    } as any);
    expect(ctx.ui.notify).not.toHaveBeenCalled();
  });

  it("notifica quando passa do threshold", async () => {
    const ctx = makeCtx({ thresholdMin: 1 });
    await handler(ctx as any, {
      sessionId: "s1",
      oldStatus: "running",
      newStatus: "awaiting-input",
      durationMs: 90 * 1000,
    } as any);
    expect(ctx.ui.notify).toHaveBeenCalledTimes(1);
  });
});

function makeCtx(opts: { thresholdMin: number }) {
  return {
    config: { get: async () => opts.thresholdMin },
    sessions: { get: async () => ({ workspaceName: "ws", lastMessage: "msg" }) },
    ui: { notify: jest.fn() },
  };
}
