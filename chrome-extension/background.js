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
  chrome.action.setBadgeText({ tabId, text: shortBranch(entry.branch) || "•" });
  chrome.action.setBadgeBackgroundColor({
    tabId,
    color: isWt ? "#e5953b" : "#3fa55f",
  });
  chrome.action.setTitle({
    tabId,
    title:
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
