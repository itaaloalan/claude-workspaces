// Pill flutuante nos CANTOS da página (estilo widget de FPS):
// 🌿 branch + selo worktree/principal. Laranja = worktree isolado;
// verde = repo principal.
//
// - Clique no pill → menu: 🎯 Ir para a sessão do Claude · 📂 Abrir pasta
//   · mover entre os 4 cantos.
// - O canto escolhido PERSISTE (chrome.storage.local) — refresh volta na
//   última posição. O ✕ esconde só nesta aba até o próximo load.

const BAR_ID = "__cw_worktree_bar__";
const MENU_ID = "__cw_worktree_menu__";
const SERVER = "http://127.0.0.1:43210";
const CORNERS = {
  tl: { top: "14px", left: "14px" },
  tr: { top: "14px", right: "14px" },
  bl: { bottom: "14px", left: "14px" },
  br: { bottom: "14px", right: "14px" },
};

let dismissed = false; // por aba/load — refresh volta a mostrar
let corner = "br";
let lastEntry = null;

try {
  chrome.storage.local.get({ cw_corner: "br" }, (v) => {
    corner = CORNERS[v.cw_corner] ? v.cw_corner : "br";
    if (lastEntry) renderBar(lastEntry);
  });
} catch (_e) {}

function tabPort() {
  return location.port || (location.protocol === "https:" ? "443" : "80");
}

function callServer(path) {
  fetch(`${SERVER}${path}?port=${tabPort()}`, { cache: "no-store" }).catch(
    () => {}
  );
}

function removeMenu() {
  const el = document.getElementById(MENU_ID);
  if (el) el.remove();
}

function removeBar() {
  removeMenu();
  const el = document.getElementById(BAR_ID);
  if (el) el.remove();
}

function cornerCss(extraGap) {
  const c = CORNERS[corner] || CORNERS.br;
  const parts = [];
  for (const [k, v] of Object.entries(c)) {
    parts.push(`${k}:${extraGap ? `calc(${v} + ${extraGap}px)` : v}`);
  }
  return parts.join(";");
}

function setCorner(next) {
  corner = CORNERS[next] ? next : "br";
  try {
    chrome.storage.local.set({ cw_corner: corner });
  } catch (_e) {}
  if (lastEntry) renderBar(lastEntry);
}

function buildMenu(accent) {
  removeMenu();
  const menu = document.createElement("div");
  menu.id = MENU_ID;
  menu.style.cssText = [
    "position:fixed", "z-index:2147483647", cornerCss(38),
    "display:flex", "flex-direction:column", "min-width:230px",
    "padding:4px", "border-radius:9px",
    "font:500 12px system-ui,sans-serif", "color:#e6e6e6",
    "background:rgba(20,20,20,.97)", `border:1px solid ${accent}`,
    "box-shadow:0 4px 14px rgba(0,0,0,.5)", "user-select:none",
  ].join(";");

  const itemCss =
    "padding:7px 10px;border-radius:6px;cursor:pointer;white-space:nowrap";
  const hover = (el) => {
    el.addEventListener("mouseenter", () => (el.style.background = "#2a2a2a"));
    el.addEventListener("mouseleave", () => (el.style.background = ""));
  };

  const goSession = document.createElement("div");
  goSession.textContent = "🎯 Ir para a sessão do Claude";
  goSession.style.cssText = itemCss;
  hover(goSession);
  goSession.addEventListener("click", (ev) => {
    ev.stopPropagation();
    callServer("/focus");
    removeMenu();
  });
  menu.appendChild(goSession);

  const openFolder = document.createElement("div");
  openFolder.textContent = "📂 Abrir pasta do worktree";
  openFolder.style.cssText = itemCss;
  hover(openFolder);
  openFolder.addEventListener("click", (ev) => {
    ev.stopPropagation();
    callServer("/open");
    removeMenu();
  });
  menu.appendChild(openFolder);

  const sep = document.createElement("div");
  sep.style.cssText = "height:1px;background:#333;margin:4px 6px";
  menu.appendChild(sep);

  const moveRow = document.createElement("div");
  moveRow.style.cssText =
    "display:flex;align-items:center;gap:4px;padding:4px 10px";
  const moveLabel = document.createElement("span");
  moveLabel.textContent = "Mover:";
  moveLabel.style.cssText = "opacity:.7;margin-right:2px";
  moveRow.appendChild(moveLabel);
  for (const [key, arrow] of [
    ["tl", "↖"], ["tr", "↗"], ["bl", "↙"], ["br", "↘"],
  ]) {
    const b = document.createElement("span");
    b.textContent = arrow;
    b.style.cssText =
      "cursor:pointer;padding:2px 7px;border-radius:5px;" +
      (key === corner
        ? `background:${accent};color:#111;font-weight:700`
        : "background:#2a2a2a");
    b.title = "Mover pra este canto (posição é lembrada)";
    b.addEventListener("click", (ev) => {
      ev.stopPropagation();
      setCorner(key);
    });
    moveRow.appendChild(b);
  }
  menu.appendChild(moveRow);

  document.documentElement.appendChild(menu);
  // Clique fora fecha.
  setTimeout(() => {
    const closeOnOutside = (ev) => {
      const m = document.getElementById(MENU_ID);
      if (m && !m.contains(ev.target)) {
        removeMenu();
        document.removeEventListener("click", closeOnOutside, true);
      }
    };
    document.addEventListener("click", closeOnOutside, true);
  }, 0);
}

function renderBar(entry) {
  lastEntry = entry;
  removeBar();
  if (!entry || dismissed) return;
  const isWt = Boolean(entry.worktree);
  const accent = isWt ? "#e5953b" : "#3fa55f";
  const pill = document.createElement("div");
  pill.id = BAR_ID;
  pill.style.cssText = [
    "position:fixed", cornerCss(0), "z-index:2147483647",
    "display:flex", "align-items:center", "gap:7px",
    "padding:5px 10px", "border-radius:9px",
    "font:600 12px system-ui,sans-serif", "color:#e6e6e6",
    "background:rgba(20,20,20,.92)", `border:1px solid ${accent}`,
    "box-shadow:0 2px 10px rgba(0,0,0,.45)",
    "max-width:46vw", "cursor:pointer", "user-select:none",
  ].join(";");
  pill.title =
    `${entry.workspace} / ${entry.runner}` +
    (entry.scope === "console" ? " (console)" : "") +
    (entry.branch ? ` · 🌿 ${entry.branch}` : "") +
    (isWt ? " · worktree" : " · repo principal") +
    "\nClique: menu (sessão, pasta, mover)";

  pill.addEventListener("click", () => {
    if (document.getElementById(MENU_ID)) removeMenu();
    else buildMenu(accent);
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
  close.title = "Esconder nesta aba (volta no próximo load)";
  close.addEventListener("click", (ev) => {
    ev.stopPropagation();
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
