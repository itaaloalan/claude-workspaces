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

// Canto por SISTEMA (host:porta): mover o pill aqui não mexe nos outros
// apps. Fallback pro global "cw_corner" e por fim "br".
const CORNER_KEY = `cw_corner:${location.host}`;
try {
  chrome.storage.local.get({ [CORNER_KEY]: "", cw_corner: "br" }, (v) => {
    const chosen = v[CORNER_KEY] || v.cw_corner || "br";
    corner = CORNERS[chosen] ? chosen : "br";
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
    chrome.storage.local.set({ [CORNER_KEY]: corner });
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

  // Console espelhado — só quando o runner pertence a um console Claude.
  if (lastEntry && lastEntry.console_session_id && lastEntry._token) {
    const openConsole = document.createElement("div");
    openConsole.textContent = "💻 Abrir console do Claude aqui";
    openConsole.style.cssText = itemCss;
    hover(openConsole);
    openConsole.addEventListener("click", (ev) => {
      ev.stopPropagation();
      openConsoleOverlay();
      removeMenu();
    });
    menu.appendChild(openConsole);

    const openWin = document.createElement("div");
    openWin.textContent = "↗ Console em janela separada";
    openWin.style.cssText = itemCss;
    hover(openWin);
    openWin.addEventListener("click", (ev) => {
      ev.stopPropagation();
      window.open(consoleUrl(), "_blank", "width=980,height=640");
      removeMenu();
    });
    menu.appendChild(openWin);
  }

  // Runners do mesmo console/escopo — mostra quem está em qual worktree, com
  // ⚠ nos que divergem (mesmo repo, branch diferente). Outro repo = neutro.
  if (
    lastEntry &&
    Array.isArray(lastEntry.scope_runners) &&
    lastEntry.scope_runners.length >= 2
  ) {
    const sepS = document.createElement("div");
    sepS.style.cssText = "height:1px;background:#333;margin:4px 6px";
    menu.appendChild(sepS);

    const head = document.createElement("div");
    head.textContent = lastEntry.scope_mismatch
      ? "⚠ Runners em worktrees diferentes"
      : "Runners deste console";
    head.style.cssText =
      "padding:5px 10px 2px;font-size:11px;" +
      (lastEntry.scope_mismatch
        ? "color:#e0b020;font-weight:700"
        : "opacity:.65");
    menu.appendChild(head);

    for (const r of lastEntry.scope_runners) {
      const row = document.createElement("div");
      row.textContent =
        `${r.ok ? "✓" : "⚠"} ${r.runner}` + (r.branch ? ` · ${r.branch}` : "");
      row.style.cssText =
        "padding:3px 10px;white-space:nowrap;font-size:11px;" +
        (r.ok ? "color:#bdbdbd" : "color:#e0b020;font-weight:600");
      menu.appendChild(row);
    }
  }

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

const OVERLAY_ID = "__cw_console_overlay__";

function consoleUrl() {
  return (
    `${SERVER}/console?port=${tabPort()}` +
    `&token=${encodeURIComponent((lastEntry && lastEntry._token) || "")}`
  );
}

const CONSOLE_SIZE_KEY = `cw_console_size:${location.host}`;

function openConsoleOverlay() {
  const old = document.getElementById(OVERLAY_ID);
  if (old) {
    old.remove();
    return;
  }
  const wrap = document.createElement("div");
  wrap.id = OVERLAY_ID;
  wrap.style.cssText = [
    "position:fixed", "z-index:2147483646",
    "right:14px", "bottom:48px", "width:min(900px,72vw)",
    "height:min(560px,70vh)", "display:flex", "flex-direction:column",
    "border-radius:10px", "overflow:hidden",
    "border:1px solid #3a3a3a", "box-shadow:0 8px 30px rgba(0,0,0,.6)",
    "background:#0e0e0e",
  ].join(";");
  // Tamanho lembrado POR SISTEMA (host:porta) — mesmo padrão do canto.
  try {
    chrome.storage.local.get({ [CONSOLE_SIZE_KEY]: null }, (v) => {
      const s = v[CONSOLE_SIZE_KEY];
      if (s && s.w && s.h) {
        wrap.style.width = `${s.w}px`;
        wrap.style.height = `${s.h}px`;
      }
    });
  } catch (_e) {}

  const head = document.createElement("div");
  head.style.cssText =
    "flex:none;display:flex;align-items:center;gap:8px;padding:4px 10px;" +
    "background:#1b1b1b;color:#c8c8c8;font:600 12px system-ui,sans-serif";
  const t = document.createElement("span");
  t.textContent = "💻 Console do Claude (espelho)";
  head.appendChild(t);
  const spacer = document.createElement("span");
  spacer.style.cssText = "flex:1";
  head.appendChild(spacer);
  const pop = document.createElement("span");
  pop.textContent = "↗";
  pop.title = "Abrir em janela separada";
  pop.style.cssText = "cursor:pointer;opacity:.7;padding:0 6px";
  pop.addEventListener("click", () => {
    window.open(consoleUrl(), "_blank", "width=980,height=640");
    wrap.remove();
  });
  head.appendChild(pop);
  const x = document.createElement("span");
  x.textContent = "✕";
  x.style.cssText = "cursor:pointer;opacity:.7;padding:0 4px";
  x.addEventListener("click", () => wrap.remove());
  head.appendChild(x);
  wrap.appendChild(head);

  const frame = document.createElement("iframe");
  frame.src = consoleUrl();
  frame.style.cssText = "flex:1;border:0;width:100%;background:#0e0e0e";
  wrap.appendChild(frame);

  // Handle de resize no canto SUPERIOR ESQUERDO (o overlay é ancorado
  // embaixo-direita: arrastar pra cima/esquerda = crescer). Durante o
  // drag o iframe perde pointer-events (senão engole o mousemove).
  const grip = document.createElement("div");
  grip.title = "Arrastar pra redimensionar";
  grip.style.cssText = [
    "position:absolute", "top:0", "left:0", "width:16px", "height:16px",
    "cursor:nwse-resize", "z-index:2",
    "background:linear-gradient(135deg,#777 0 2px,transparent 2px 5px," +
      "#777 5px 7px,transparent 7px)",
    "border-top-left-radius:10px", "opacity:.7",
  ].join(";");
  wrap.style.position = "fixed"; // garante o contexto do absolute
  wrap.appendChild(grip);

  grip.addEventListener("mousedown", (down) => {
    down.preventDefault();
    down.stopPropagation();
    const rect = wrap.getBoundingClientRect();
    const right = rect.right;
    const bottom = rect.bottom;
    frame.style.pointerEvents = "none";
    const onMove = (mv) => {
      const w = Math.min(
        Math.max(right - mv.clientX, 380), window.innerWidth * 0.95
      );
      const h = Math.min(
        Math.max(bottom - mv.clientY, 260), window.innerHeight * 0.9
      );
      wrap.style.width = `${Math.round(w)}px`;
      wrap.style.height = `${Math.round(h)}px`;
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove, true);
      document.removeEventListener("mouseup", onUp, true);
      frame.style.pointerEvents = "";
      try {
        chrome.storage.local.set({
          [CONSOLE_SIZE_KEY]: {
            w: Math.round(wrap.getBoundingClientRect().width),
            h: Math.round(wrap.getBoundingClientRect().height),
          },
        });
      } catch (_e) {}
    };
    document.addEventListener("mousemove", onMove, true);
    document.addEventListener("mouseup", onUp, true);
  });

  document.documentElement.appendChild(wrap);
}

// Carimbo de commit do build na página (Detecção B). O build/deploy injeta
// <meta name="cw-build-commit" content="<sha>"> no <head>; sem a tag, B fica
// desligado pra esse projeto (sem falso alarme).
function buildCommitFromPage() {
  const m = document.querySelector('meta[name="cw-build-commit"]');
  return m && m.content ? m.content.trim() : "";
}

// Alerta "deploy fora do worktree": A) o app detectou que a porta é servida
// de outra pasta (entry.served_mismatch); B) o commit carimbado no build não
// bate com o HEAD atual do worktree. Retorna {reason} ou null.
function deployAlert(entry) {
  if (!entry) return null;
  if (entry.served_mismatch) {
    return { reason: `deploy fora do worktree — servido de ${entry.served_cwd || "outra pasta"}` };
  }
  const stamp = buildCommitFromPage();
  const head = (entry.head_commit || "").trim();
  if (stamp && head && !stamp.startsWith(head) && !head.startsWith(stamp)) {
    return { reason: `build desatualizado (${stamp} ≠ HEAD ${head})` };
  }
  return null;
}

function renderBar(entry) {
  lastEntry = entry;
  removeBar();
  if (!entry || dismissed) return;
  const isWt = Boolean(entry.worktree);
  const alert = deployAlert(entry);
  // Worktrees divergentes no escopo (api/web em pastas diferentes) — âmbar,
  // distinto do vermelho de deploy (que tem prioridade).
  const scopeWarn = !alert && Boolean(entry.scope_mismatch);
  const accent = alert
    ? "#e05252"
    : scopeWarn ? "#e0b020" : (isWt ? "#e5953b" : "#3fa55f");
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
    (alert ? `⚠ ${alert.reason}\n` : "") +
    (scopeWarn ? "⚠ runners deste app em worktrees diferentes (veja o menu)\n" : "") +
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
  kind.textContent = alert
    ? "⚠ deploy"
    : scopeWarn ? "⚠ worktrees" : (isWt ? "worktree" : "principal");
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
