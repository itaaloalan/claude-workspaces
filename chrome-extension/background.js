// Service worker: consulta o StateServer do claude-workspaces e aplica o
// badge por aba. A faixa no topo da página é renderizada pelo content.js
// (que recebe a entry via mensagem).

const STATE_URL = "http://127.0.0.1:43210/state.json";
const CACHE_MS = 3000;

let cache = { ts: 0, data: null };

async function fetchState() {
  const now = Date.now();
  if (cache.data && now - cache.ts < CACHE_MS) return cache.data;
  try {
    const resp = await fetch(STATE_URL, { cache: "no-store" });
    if (!resp.ok) throw new Error(String(resp.status));
    cache = { ts: now, data: await resp.json() };
  } catch (_e) {
    cache = { ts: now, data: null }; // app fechado → sem badge
  }
  return cache.data;
}

function portFromUrl(rawUrl) {
  try {
    const u = new URL(rawUrl);
    if (u.hostname !== "localhost" && u.hostname !== "127.0.0.1") return null;
    if (u.port) return u.port;
    return u.protocol === "https:" ? "443" : "80";
  } catch (_e) {
    return null;
  }
}

function shortBranch(branch) {
  if (!branch) return "";
  const name = branch.includes("/") ? branch.split("/").pop() : branch;
  return name.slice(0, 4);
}

// Runners do MESMO escopo (console, senão workspace) que a aba atual, pra
// avisar quando api/web/etc. estão em worktrees diferentes. Agrupa por `repo`
// (git common-dir, vindo do backend): só conta divergência DENTRO do mesmo
// repo — o `manager` é de outro repo e às vezes tem o mesmo nome de branch.
function computeScope(ports, entry) {
  const scopeId = entry.console_session_id || entry.workspace_id || "";
  if (!scopeId) return { scope_runners: [], scope_mismatch: false };
  const seen = new Set();
  const runners = [];
  for (const e of Object.values(ports || {})) {
    const eid = e.console_session_id || e.workspace_id || "";
    if (eid !== scopeId) continue;
    const rid = e.runner_id || `${e.runner}|${e.cwd}`;
    if (seen.has(rid)) continue;
    seen.add(rid);
    const sameRepo = Boolean(entry.repo) && e.repo === entry.repo;
    runners.push({
      runner: e.runner || "(runner)",
      branch: e.branch || "",
      worktree: Boolean(e.worktree),
      sameRepo,
      ok: !sameRepo || (e.branch || "") === (entry.branch || ""),
    });
  }
  const branches = new Set(
    runners.filter((r) => r.sameRepo).map((r) => r.branch).filter(Boolean)
  );
  return { scope_runners: runners, scope_mismatch: branches.size > 1 };
}

async function refreshTab(tabId, url) {
  const port = portFromUrl(url || "");
  if (!port) {
    chrome.action.setBadgeText({ tabId, text: "" });
    return;
  }
  const state = await fetchState();
  const entry = state && state.ports ? state.ports[port] : null;
  if (!entry) {
    chrome.action.setBadgeText({ tabId, text: "" });
    try {
      await chrome.tabs.sendMessage(tabId, { kind: "cw-state", entry: null });
    } catch (_e) {} // página sem content script (ainda carregando etc.)
    return;
  }
  const isWt = Boolean(entry.worktree);
  // Token do app vai junto — os endpoints /console/* exigem.
  entry._token = (state && state.token) || "";
  // Irmãos do escopo (api/web/...) + aviso de worktrees divergentes.
  const scope = computeScope(state.ports, entry);
  entry.scope_runners = scope.scope_runners;
  entry.scope_mismatch = scope.scope_mismatch;
  // Detecção A: o app sabe que a porta é servida de outra pasta → badge
  // vermelho ⚠. (A Detecção B — build desatualizado — fica na pill do
  // content.js, que tem acesso ao carimbo da página.)
  const mismatch = Boolean(entry.served_mismatch);
  chrome.action.setBadgeText({
    tabId,
    text: mismatch ? "⚠" : (shortBranch(entry.branch) || "•"),
  });
  chrome.action.setBadgeBackgroundColor({
    tabId,
    color: mismatch ? "#e05252" : (isWt ? "#e5953b" : "#3fa55f"),
  });
  chrome.action.setTitle({
    tabId,
    title:
      (mismatch
        ? `⚠ deploy fora do worktree — servido de ${entry.served_cwd || "outra pasta"}\n`
        : "") +
      (!mismatch && entry.scope_mismatch
        ? "⚠ runners deste app em worktrees diferentes\n"
        : "") +
      `${entry.workspace} · ${entry.runner}` +
      (entry.branch ? ` · 🌿 ${entry.branch}` : "") +
      (isWt ? " (worktree)" : ""),
  });
  try {
    await chrome.tabs.sendMessage(tabId, { kind: "cw-state", entry });
  } catch (_e) {}
}

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  try {
    const tab = await chrome.tabs.get(tabId);
    refreshTab(tabId, tab.url);
  } catch (_e) {}
});

chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
  if (info.status === "complete" || info.url) refreshTab(tabId, tab.url);
});

// Content script pede o estado ao carregar (cobre raça com onUpdated).
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.kind === "cw-get-state" && sender.tab) {
    refreshTab(sender.tab.id, sender.tab.url);
  }
  sendResponse && sendResponse({});
});
