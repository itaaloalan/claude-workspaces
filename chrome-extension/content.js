// Faixa no topo da página: 🌿 branch — worktree · workspace/runner.
// Laranja = worktree isolado; verde = repo principal. O ✕ esconde a
// faixa pra aquela aba (volta no próximo load).

const BAR_ID = "__cw_worktree_bar__";
let dismissed = false;

function removeBar() {
  const el = document.getElementById(BAR_ID);
  if (el) el.remove();
  document.documentElement.style.removeProperty("margin-top");
}

function renderBar(entry) {
  removeBar();
  if (!entry || dismissed) return;
  const isWt = Boolean(entry.worktree);
  const bar = document.createElement("div");
  bar.id = BAR_ID;
  bar.style.cssText = [
    "position:fixed", "top:0", "left:0", "right:0", "z-index:2147483647",
    "height:24px", "line-height:24px", "padding:0 10px",
    "font:600 12px/24px system-ui,sans-serif",
    "display:flex", "align-items:center", "gap:8px",
    "color:#fff", "box-shadow:0 1px 4px rgba(0,0,0,.35)",
    `background:${isWt ? "#b06a14" : "#2e7d4f"}`,
  ].join(";");

  const label = document.createElement("span");
  label.style.cssText = "flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
  const branch = entry.branch ? `🌿 ${entry.branch}` : "";
  const kind = isWt ? "worktree" : "principal";
  label.textContent =
    `${branch}${branch ? " — " : ""}${kind} · ` +
    `${entry.workspace} / ${entry.runner}` +
    (entry.scope === "console" ? " (console)" : "");
  bar.appendChild(label);

  const close = document.createElement("span");
  close.textContent = "✕";
  close.style.cssText = "cursor:pointer;opacity:.8;padding:0 4px";
  close.title = "Esconder nesta aba";
  close.addEventListener("click", () => {
    dismissed = true;
    removeBar();
  });
  bar.appendChild(close);

  document.documentElement.appendChild(bar);
  // Empurra a página pra baixo pra faixa não cobrir headers fixos.
  document.documentElement.style.setProperty("margin-top", "24px", "important");
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.kind === "cw-state") renderBar(msg.entry);
});

// Pede o estado ao carregar (cobre a raça com o onUpdated do background).
try {
  chrome.runtime.sendMessage({ kind: "cw-get-state" }, () => void chrome.runtime.lastError);
} catch (_e) {}
