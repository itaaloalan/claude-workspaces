// Pill flutuante no canto inferior direito (estilo widget de FPS):
// 🌿 branch + selo worktree/principal. Laranja = worktree isolado;
// verde = repo principal. O ✕ esconde pra aquela aba (volta no próximo
// load). Flutuante de propósito: faixa full-width cobria navbars/footers
// position:fixed dos apps.

const BAR_ID = "__cw_worktree_bar__";
let dismissed = false;

function removeBar() {
  const el = document.getElementById(BAR_ID);
  if (el) el.remove();
}

function renderBar(entry) {
  removeBar();
  if (!entry || dismissed) return;
  const isWt = Boolean(entry.worktree);
  const accent = isWt ? "#e5953b" : "#3fa55f";
  const pill = document.createElement("div");
  pill.id = BAR_ID;
  pill.style.cssText = [
    "position:fixed", "bottom:14px", "right:14px", "z-index:2147483647",
    "display:flex", "align-items:center", "gap:7px",
    "padding:5px 10px", "border-radius:9px",
    "font:600 12px system-ui,sans-serif", "color:#e6e6e6",
    "background:rgba(20,20,20,.92)",
    `border:1px solid ${accent}`,
    "box-shadow:0 2px 10px rgba(0,0,0,.45)",
    "max-width:46vw", "cursor:pointer", "user-select:none",
  ].join(";");
  pill.title =
    `${entry.workspace} / ${entry.runner}` +
    (entry.scope === "console" ? " (console)" : "") +
    (entry.branch ? ` · 🌿 ${entry.branch}` : "") +
    (isWt ? " · worktree" : " · repo principal") +
    "\nClique: abrir a pasta no gerenciador de arquivos";

  // Clique no pill (fora do ✕) → app abre o explorer no cwd do runner.
  pill.addEventListener("click", () => {
    const port = location.port || (location.protocol === "https:" ? "443" : "80");
    fetch(`http://127.0.0.1:43210/open?port=${port}`, { cache: "no-store" })
      .catch(() => {});
  });

  const dot = document.createElement("span");
  dot.style.cssText =
    `width:8px;height:8px;border-radius:50%;background:${accent};flex:none`;
  pill.appendChild(dot);

  const label = document.createElement("span");
  label.style.cssText =
    "overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
  label.textContent = entry.branch
    ? `🌿 ${entry.branch}`
    : `${entry.workspace} / ${entry.runner}`;
  pill.appendChild(label);

  const kind = document.createElement("span");
  kind.style.cssText =
    `flex:none;font-size:10px;font-weight:700;color:${accent};` +
    "text-transform:uppercase;letter-spacing:.4px";
  kind.textContent = isWt ? "worktree" : "principal";
  pill.appendChild(kind);

  const close = document.createElement("span");
  close.textContent = "✕";
  close.style.cssText =
    "cursor:pointer;opacity:.55;padding:0 0 0 2px;flex:none";
  close.title = "Esconder nesta aba";
  close.addEventListener("click", (ev) => {
    ev.stopPropagation(); // não dispara o "abrir pasta" do pill
    dismissed = true;
    removeBar();
  });
  pill.appendChild(close);

  document.documentElement.appendChild(pill);
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.kind === "cw-state") renderBar(msg.entry);
});

// Pede o estado ao carregar (cobre a raça com o onUpdated do background).
try {
  chrome.runtime.sendMessage({ kind: "cw-get-state" }, () => void chrome.runtime.lastError);
} catch (_e) {}
