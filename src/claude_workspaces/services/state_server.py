"""StateServer — endpoint HTTP local pro plugin de browser.

Serve em 127.0.0.1 (`/state.json`) o mapa porta → runner/workspace/worktree
que a extensão Chrome usa pra mostrar badge + faixa quando uma aba
localhost:<porta> pertence a um runner do app (e se ele roda num
worktree). Read-only, localhost-only, ligável nas Settings.

A UI empurra snapshots baratos (sem git) via `update()`; o
enriquecimento de branch/worktree roda na thread do handler com cache
TTL — `is_worktree_path`/`current_branch` não tocam em Qt.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Origens autorizadas a LER as respostas (CORS): páginas locais (os apps
# em localhost:<porta>) e a extensão. Sites da internet (evil.com) não
# recebem ACAO → o browser bloqueia a leitura — sem isso o /state.json
# (paths, branches e o token dos /console/*) vazaria pra qualquer site.
_LOCAL_ORIGIN_RE = re.compile(
    r"^(chrome-extension://[a-p]{32}"
    r"|https?://(localhost|127\.0\.0\.1)(:\d+)?)$"
)

log = logging.getLogger(__name__)

DEFAULT_PORT = 43210

# Assets servidos em /static/<nome> — whitelist explícita (sem traversal).
_STATIC_DIR = Path(__file__).resolve().parents[1] / "ui" / "static" / "vendor"
_STATIC_WHITELIST = {
    "xterm.js": "application/javascript",
    "addon-fit.js": "application/javascript",
    "xterm.css": "text/css",
}

# Raiz do worktree num path tipo `<repo>.claude/<worktree>/src/web` → o segmento
# `<repo>.claude/<worktree>` (primeiro `.claude/<dir>`). "" quando não há.
_WORKTREE_ROOT_RE = re.compile(r"^(.*?\.claude/[^/]+)")


def _worktree_root(path: str) -> str:
    m = _WORKTREE_ROOT_RE.match(path)
    return m.group(1) if m else ""


def _find_serving_entry(ports: dict, current_port: str, served_cwd: str) -> dict | None:
    """Acha, no snapshot, o runner que de fato serve `served_cwd` — pra
    reatribuir a exibição da porta a ele (e não ao runner morto que ficou
    segurando a chave). Casa por path normalizado exato ou mesma raiz de
    worktree; prioriza state=="running" e match exato."""
    target = os.path.normpath(served_cwd)
    target_root = _worktree_root(target)
    best: tuple[dict, bool, bool] | None = None  # (entry, running, exact)
    for p, e in ports.items():
        if p == current_port:
            continue
        cwd = e.get("cwd") or ""
        if not cwd:
            continue
        cwd = os.path.normpath(cwd)
        exact = cwd == target
        if not (exact or (target_root and _worktree_root(cwd) == target_root)):
            continue
        running = e.get("state") == "running"
        if best is None or (running, exact) > (best[1], best[2]):
            best = (e, running, exact)
    return best[0] if best else None


class StateServer:
    def __init__(self, port: int = DEFAULT_PORT, host: str = "127.0.0.1") -> None:
        self._host = host
        self._port = port
        self._lock = threading.Lock()
        self._snapshot: dict = {"ports": {}}
        # cwd → (expira_em, {"branch": ..., "worktree": ...})
        self._branch_cache: dict[str, tuple[float, dict]] = {}
        self._httpd: ThreadingHTTPServer | None = None
        # Callback de "Ir para a sessão" (entry do snapshot) — injetado
        # pela main_window via um Signal.emit (thread-safe: a emissão de
        # outra thread vira queued connection na UI thread).
        self._focus_cb = None
        # Espelho de console no browser: hub injetado pela main_window.
        # Endpoints /console/* exigem este token (input remoto numa sessão
        # Claude não fica aberto a qualquer página local) — distribuído
        # via /state.json pra extensão.
        self._hub = None
        self.token = uuid.uuid4().hex
        # Detecção "deploy fora do worktree" (served_proc): port(str) → info
        # {served_pid, served_cwd, served_mismatch}. Recalculado por uma thread
        # de fundo (subprocess ss/lsof/git — fora de qualquer thread Qt) e lido
        # tanto pelo _payload (pill da extensão) quanto pelo app (indicador no
        # runner). Funciona mesmo sem aba aberta no browser.
        self._served: dict[str, dict] = {}
        self._served_thread: threading.Thread | None = None
        self._served_stop = threading.Event()

    # ---- ciclo de vida -----------------------------------------------------

    def start(self) -> bool:
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            def _acao(self) -> str | None:
                """Anti DNS-rebinding + CORS: Host precisa ser local;
                Origin (quando presente) precisa ser local/extensão.
                Retorna o valor do header ACAO ("" = sem header, ex:
                curl local) ou None pra rejeitar com 403."""
                host = (self.headers.get("Host") or "").split(":")[0]
                if host not in ("localhost", "127.0.0.1"):
                    return None
                origin = self.headers.get("Origin") or ""
                if not origin:
                    return ""
                if _LOCAL_ORIGIN_RE.match(origin):
                    return origin
                return None

            def _deny(self) -> None:
                self.send_response(403)
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802 (API do http.server)
                acao = self._acao()
                if acao is None:
                    self._deny()
                    return
                path = self.path.split("?")[0]
                if path == "/state.json":
                    body = json.dumps(
                        outer._payload(), ensure_ascii=False
                    ).encode("utf-8")
                    self.send_response(200)
                    self.send_header(
                        "Content-Type", "application/json; charset=utf-8"
                    )
                    if acao:
                        self.send_header("Access-Control-Allow-Origin", acao)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if path == "/open":
                    ok = outer._open_folder(self.path)
                    self.send_response(204 if ok else 404)
                    if acao:
                        self.send_header("Access-Control-Allow-Origin", acao)
                    self.end_headers()
                    return
                if path == "/focus":
                    ok = outer._request_focus(self.path)
                    self.send_response(204 if ok else 404)
                    if acao:
                        self.send_header("Access-Control-Allow-Origin", acao)
                    self.end_headers()
                    return
                if path.startswith("/static/"):
                    outer._serve_static(self, path)
                    return
                if path == "/runner/restart":
                    outer._handle_runner_restart(self, acao)
                    return
                if path == "/console":
                    outer._serve_console_page(self)
                    return
                if path == "/console/stream":
                    outer._serve_console_stream(self, acao)
                    return
                if path == "/console/size":
                    outer._serve_console_size(self, acao)
                    return
                self.send_response(404)
                self.end_headers()

            def do_POST(self) -> None:  # noqa: N802 (API do http.server)
                acao = self._acao()
                if acao is None:
                    self._deny()
                    return
                if self.path.split("?")[0] == "/console/input":
                    outer._handle_console_input(self, acao)
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, *args) -> None:  # silencia stderr
                pass

        try:
            self._httpd = ThreadingHTTPServer((self._host, self._port), _Handler)
        except OSError as e:
            log.warning(
                "StateServer não subiu em %s:%d (%s) — plugin de browser "
                "fica sem dados", self._host, self._port, e,
            )
            self._httpd = None
            return False
        thread = threading.Thread(
            target=self._httpd.serve_forever, name="state-server", daemon=True
        )
        thread.start()
        self._served_stop.clear()
        self._served_thread = threading.Thread(
            target=self._served_loop, name="state-server-served", daemon=True
        )
        self._served_thread.start()
        log.info("StateServer em http://%s:%d/state.json", self._host, self._port)
        return True

    def stop(self) -> None:
        self._served_stop.set()
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                log.debug("shutdown do StateServer falhou", exc_info=True)
            self._httpd = None

    def _served_loop(self) -> None:
        """Recalcula a cada ~3s, fora de qualquer thread Qt, se o processo que
        escuta cada porta roda do worktree esperado (Detecção A). Resultado em
        self._served, consumido pelo _payload (pill) e por served_info() (app)."""
        from .served_proc import served_mismatch
        while not self._served_stop.wait(3.0):
            with self._lock:
                ports = {
                    p: (e.get("cwd") or "")
                    for p, e in self._snapshot.get("ports", {}).items()
                }
            computed: dict[str, dict] = {}
            for port, cwd in ports.items():
                if not cwd or not port.isdigit():
                    continue  # chaves sintéticas (r:<id>) não têm porta TCP
                try:
                    computed[port] = served_mismatch(cwd, int(port))
                except Exception:
                    log.debug("served_mismatch falhou pra :%s", port, exc_info=True)
            with self._lock:
                self._served = computed

    def served_info(self) -> dict[str, dict]:
        """Cópia do served-info por porta (lido pelo app na UI thread)."""
        with self._lock:
            return {p: dict(v) for p, v in self._served.items()}

    @property
    def running(self) -> bool:
        return self._httpd is not None

    # ---- dados ---------------------------------------------------------------

    def update(self, snapshot: dict) -> None:
        """Snapshot {"ports": {"4202": {workspace, runner, scope, cwd,
        status...}}} — empurrado pela UI thread (sem git aqui)."""
        with self._lock:
            self._snapshot = snapshot

    def set_hub(self, hub) -> None:
        """ConsoleHub (espelho do PTY) — injetado pela main_window."""
        self._hub = hub

    def set_restart_callback(self, fn) -> None:
        """`fn(entry)` — "↻ Reiniciar runner" do espelho; passe Signal.emit."""
        self._restart_cb = fn

    def _handle_runner_restart(self, handler, acao: str = "") -> None:
        q = self._query(handler.path)
        if q.get("token", "") != self.token:
            handler.send_response(403)
            handler.end_headers()
            return
        port = q.get("port", "").strip()
        with self._lock:
            entry = dict(self._snapshot.get("ports", {}).get(port) or {})
        cb = getattr(self, "_restart_cb", None)
        ok = bool(entry.get("runner_id")) and cb is not None
        if ok:
            try:
                cb(entry)
            except Exception:
                log.warning("restart callback falhou", exc_info=True)
                ok = False
        handler.send_response(204 if ok else 404)
        if acao:
            handler.send_header("Access-Control-Allow-Origin", acao)
        handler.end_headers()

    def _payload(self) -> dict:
        with self._lock:
            snap = json.loads(json.dumps(self._snapshot))  # deep copy barato
            served = {p: dict(v) for p, v in self._served.items()}
        ports_map = snap.get("ports", {})
        # 1ª passada: resolve branch/worktree/head_commit de cada entry (cache
        # TTL). Tem que vir ANTES da reatribuição — esta copia o branch já
        # resolvido do runner que realmente serve a porta (pode aparecer depois
        # no dict).
        for entry in ports_map.values():
            cwd = entry.get("cwd") or ""
            if cwd:
                entry.update(self._branch_info(cwd))
        # 2ª passada: Detecção A + reatribuição ao worktree realmente servido.
        for port, entry in ports_map.items():
            si = served.get(port)
            if not si:
                continue
            smatch = bool(si.get("served_mismatch"))
            scwd = si.get("served_cwd") or ""
            entry["served_cwd"] = scwd
            if not (smatch and scwd):
                entry["served_mismatch"] = smatch
                continue
            # A pill tem que mostrar o worktree REALMENTE servido — não o do
            # runner que (talvez morto) ainda segura a chave da porta por causa
            # de uma `_current_url` retida. Reatribui a exibição ao runner vivo
            # que casa com o served_cwd; senão (zumbi fora dos runners) resolve
            # o branch direto e mantém o ⚠.
            owner = _find_serving_entry(ports_map, port, scwd)
            if owner is not None:
                for k in ("branch", "worktree", "head_commit", "cwd",
                          "state", "runner"):
                    if k in owner:
                        entry[k] = owner[k]
                # Sincroniza os campos de console pra "ir pra sessão" cair no
                # console certo (remove o do runner antigo se o owner não tem).
                entry["console_session_id"] = owner.get("console_session_id", "")
                entry["console_branch"] = owner.get("console_branch", "")
                entry["served_mismatch"] = False  # exibido == servido
            else:
                info = self._branch_info(scwd)
                if info.get("branch"):
                    entry.update(info)
                    entry["cwd"] = scwd
                entry["served_mismatch"] = True
        snap["ts"] = time.time()
        snap["token"] = self.token
        return snap

    # ---- console no browser ----------------------------------------------------

    def _query(self, raw_path: str) -> dict[str, str]:
        return {
            k: v[0]
            for k, v in parse_qs(urlparse(raw_path).query).items()
            if v
        }

    def _console_ctx(self, handler) -> dict | None:
        """Valida token e resolve a entry/sid da porta. Responde o erro
        (403/404) e retorna None quando inválido."""
        q = self._query(handler.path)
        if q.get("token", "") != self.token:
            handler.send_response(403)
            handler.end_headers()
            return None
        port = q.get("port", "").strip()
        with self._lock:
            entry = dict(self._snapshot.get("ports", {}).get(port) or {})
        sid = entry.get("console_session_id") or ""
        if not entry or not sid or self._hub is None:
            handler.send_response(404)
            handler.end_headers()
            return None
        entry["_sid"] = sid
        entry["_port"] = port
        return entry

    def _serve_static(self, handler, path: str) -> None:
        name = path[len("/static/"):]
        ctype = _STATIC_WHITELIST.get(name)
        fpath = _STATIC_DIR / name
        if ctype is None or not fpath.is_file():
            handler.send_response(404)
            handler.end_headers()
            return
        body = fpath.read_bytes()
        handler.send_response(200)
        handler.send_header("Content-Type", ctype)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _serve_console_page(self, handler) -> None:
        entry = self._console_ctx(handler)
        if entry is None:
            return
        title = f"{entry.get('workspace', '')}"
        branch = entry.get("console_branch") or ""
        # Abas: Claude + cada runner DESTE console (com porta no snapshot).
        sid = entry["_sid"]
        # Geometria inicial = a do PTY do Claude (aba ativa por padrão); o
        # poll do /console/size corrige depois se o app redimensionar.
        init_size = self._hub.size(sid) if self._hub else None
        init_cols, init_rows = init_size if init_size else (80, 24)
        with self._lock:
            all_ports = dict(self._snapshot.get("ports", {}))
        tabs = [{"label": "🤖 Claude", "target": "claude",
                 "port": entry["_port"]}]
        for p, e in sorted(all_ports.items()):
            if e.get("console_session_id") == sid and e.get("runner_id"):
                tabs.append({
                    "label": f"⚙ {e.get('runner', p)}",
                    "target": "runner",
                    "port": p,
                })
        body = (
            _CONSOLE_HTML
            .replace("__TITLE__", title)
            .replace("__BRANCH__", branch)
            .replace("__PORT__", entry["_port"])
            .replace("__TOKEN__", self.token)
            .replace("__COLS__", str(init_cols))
            .replace("__ROWS__", str(init_rows))
            .replace("__TABS__", json.dumps(tabs, ensure_ascii=False))
        ).encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _sid_for_target(self, entry: dict) -> str | None:
        """sid do PTY pedido pela query: target=claude (default) → PTY da
        sessão; target=runner → PTY do runner DESTA porta. None se runner
        sem id."""
        target = self._query(entry["_raw_path"]).get("target", "claude")
        if target == "runner":
            rid = entry.get("runner_id") or ""
            return f"runner:{rid}" if rid else None
        return entry["_sid"]

    def _serve_console_size(self, handler, acao: str = "") -> None:
        """`/console/size?port&target&token` → {"cols":C,"rows":R} do PTY
        de origem, pro espelho do browser casar a grade (senão a TUI do
        Claude renderiza com cursor absoluto na geometria errada → texto
        sobreposto)."""
        entry = self._console_ctx(handler)
        if entry is None:
            return
        entry["_raw_path"] = handler.path
        sid = self._sid_for_target(entry)
        size = self._hub.size(sid) if sid else None
        cols, rows = size if size else (80, 24)
        body = json.dumps({"cols": cols, "rows": rows}).encode("ascii")
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Cache-Control", "no-store")
        if acao:
            handler.send_header("Access-Control-Allow-Origin", acao)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _serve_console_stream(self, handler, acao: str = "") -> None:
        entry = self._console_ctx(handler)
        if entry is None:
            return
        # target=claude (default) → PTY da sessão; target=runner → PTY do
        # runner DESTA porta (aba de logs no espelho).
        entry["_raw_path"] = handler.path
        sid = self._sid_for_target(entry)
        if sid is None:
            handler.send_response(404)
            handler.end_headers()
            return
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Cache-Control", "no-store")
        if acao:
            handler.send_header("Access-Control-Allow-Origin", acao)
        handler.end_headers()

        def _send(data: bytes) -> None:
            payload = base64.b64encode(data).decode("ascii")
            handler.wfile.write(f"data: {payload}\n\n".encode("ascii"))
            handler.wfile.flush()

        q = self._hub.subscribe(sid)
        try:
            backlog = self._hub.replay(sid)
            if backlog:
                _send(backlog)
            import queue as _queue
            while True:
                try:
                    chunk = q.get(timeout=15.0)
                    _send(chunk)
                except _queue.Empty:
                    # keep-alive (comentário SSE) — detecta cliente morto.
                    handler.wfile.write(b": ping\n\n")
                    handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # aba fechou — fim normal do stream
        finally:
            self._hub.unsubscribe(sid, q)

    def _handle_console_input(self, handler, acao: str = "") -> None:
        entry = self._console_ctx(handler)
        if entry is None:
            return
        try:
            length = int(handler.headers.get("Content-Length", "0") or 0)
        except ValueError:
            length = 0
        data = handler.rfile.read(min(length, 65536)) if length else b""
        ok = bool(data) and self._hub.write(entry["_sid"], data)
        handler.send_response(204 if ok else 404)
        if acao:
            handler.send_header("Access-Control-Allow-Origin", acao)
        handler.end_headers()

    def set_focus_callback(self, fn) -> None:
        """`fn(entry: dict)` — chamado na thread do handler; passe um
        Signal.emit pra despachar pra UI thread com segurança."""
        self._focus_cb = fn

    def _request_focus(self, raw_path: str) -> bool:
        """`/focus?port=NNNN` — pede pro app focar a sessão/console dono
        do runner daquela porta."""
        from urllib.parse import parse_qs, urlparse

        port = (
            parse_qs(urlparse(raw_path).query).get("port", [""])[0].strip()
        )
        if not port or self._focus_cb is None:
            return False
        with self._lock:
            entry = dict(self._snapshot.get("ports", {}).get(port) or {})
        if not entry:
            return False
        try:
            self._focus_cb(entry)
            return True
        except Exception:
            log.warning("focus callback falhou", exc_info=True)
            return False

    def _open_folder(self, raw_path: str) -> bool:
        """`/open?port=NNNN` — abre o cwd do runner daquela porta no
        gerenciador de arquivos (xdg-open). Só abre paths que ESTÃO no
        snapshot (nunca path arbitrário do request)."""
        import subprocess
        from pathlib import Path
        from urllib.parse import parse_qs, urlparse

        port = (
            parse_qs(urlparse(raw_path).query).get("port", [""])[0].strip()
        )
        if not port:
            return False
        with self._lock:
            entry = dict(self._snapshot.get("ports", {}).get(port) or {})
        cwd = entry.get("cwd") or ""
        if not cwd or not Path(cwd).is_dir():
            return False
        try:
            subprocess.Popen(  # noqa: S603 — path validado do snapshot
                ["xdg-open", cwd],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError:
            log.warning("xdg-open falhou pra %s", cwd, exc_info=True)
            return False

    def _branch_info(self, cwd: str) -> dict:
        now = time.monotonic()
        with self._lock:
            hit = self._branch_cache.get(cwd)
            if hit and hit[0] > now:
                return hit[1]
        info = {"branch": "", "worktree": False, "head_commit": ""}
        try:
            import subprocess

            from ..git_worktree import current_branch, is_worktree_path
            info["worktree"] = bool(is_worktree_path(cwd))
            info["branch"] = current_branch(cwd) or ""
            # HEAD curto pra Detecção B (carimbo de build vs commit atual).
            try:
                r = subprocess.run(  # noqa: S603
                    ["git", "rev-parse", "--short", "HEAD"],
                    cwd=cwd, capture_output=True, text=True, timeout=2,
                )
                if r.returncode == 0:
                    info["head_commit"] = r.stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                pass
        except Exception:
            log.debug("branch_info falhou pra %s", cwd, exc_info=True)
        with self._lock:
            # Poda expiradas no insert — sem isso o dict acumula um key por
            # cwd já visitado pra sempre (sessões longas com muitos worktrees).
            self._branch_cache = {
                k: v for k, v in self._branch_cache.items() if v[0] > now
            }
            self._branch_cache[cwd] = (now + 5.0, info)
        return info


# Página do console espelhado — placeholders __TITLE__/__BRANCH__/__PORT__/
# __TOKEN__ substituídos via str.replace (CSS/JS têm chaves demais pro
# str.format). Mesmo xterm.js vendorizado do app; output via SSE (base64),
# input via POST. O PTY é o MESMO do console embutido — o resize canônico
# é o do app (fit daqui é só visual).
_CONSOLE_HTML = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>__TITLE__ — console</title>
<link rel="stylesheet" href="/static/xterm.css">
<style>
  html, body { height: 100%; margin: 0; background: #0e0e0e; }
  body { display: flex; flex-direction: column; font-family: system-ui, sans-serif; }
  #hdr {
    flex: none; display: flex; align-items: center; gap: 8px;
    padding: 6px 10px; background: #161616; border-bottom: 1px solid #2a2a2a;
    color: #c8c8c8; font-size: 12px; font-weight: 600;
  }
  #hdr .branch { color: #5ac38a; }
  #hdr .hint { color: #777; font-weight: 400; margin-left: auto; }
  #tabs { display: flex; gap: 4px; margin-left: 10px; }
  #tabs .tab {
    padding: 2px 9px; border-radius: 6px; cursor: pointer;
    background: #222; color: #9aa0a6; border: 1px solid #2c2c2c;
  }
  #tabs .tab.active { background: #2e3b4e; color: #e6e6e6; }
  #restart {
    background: #222; color: #c8c8c8; border: 1px solid #3a3a3a;
    border-radius: 6px; padding: 2px 9px; cursor: pointer; font-size: 12px;
  }
  #restart:hover { border-color: #e5953b; color: #e5953b; }
  #term { flex: 1; min-height: 0; padding: 4px; }
  /* Scrollbar minimalista no viewport do xterm — espelha o visual dos
   * scrollbars Qt do app (8px, track transparente, thumb sutil, hover amarelo). */
  .xterm-viewport { scrollbar-width: thin; scrollbar-color: rgba(255,255,255,.16) transparent; }
  .xterm-viewport::-webkit-scrollbar { width: 8px; height: 8px; }
  .xterm-viewport::-webkit-scrollbar-track { background: transparent; }
  .xterm-viewport::-webkit-scrollbar-thumb {
    background: rgba(255,255,255,.16); border-radius: 4px; min-height: 24px;
  }
  .xterm-viewport::-webkit-scrollbar-thumb:hover { background: rgba(229,181,59,.55); }
  #off {
    display: none; position: absolute; inset: 0; align-items: center;
    justify-content: center; background: rgba(14,14,14,.85); color: #e5953b;
    font-size: 14px; z-index: 9;
  }
</style>
</head>
<body>
<div id="hdr">
  <span>__TITLE__</span>
  <span class="branch">🌿 __BRANCH__</span>
  <span id="tabs"></span>
  <button id="restart" style="display:none">↻ Reiniciar</button>
  <span class="hint">espelho do app — mesmo PTY</span>
</div>
<div id="term"></div>
<div id="off">⚠ desconectado do claude-workspaces — reabra quando o app voltar</div>
<script src="/static/xterm.js"></script>
<script>
  const PORT = "__PORT__";
  const TOKEN = "__TOKEN__";
  const TABS = __TABS__;
  const term = new Terminal({
    convertEol: false,
    fontSize: 13,
    fontFamily: "monospace",
    lineHeight: 1,
    theme: { background: "#0e0e0e", foreground: "#d8d8d8" },
    scrollback: 8000,
  });
  const termEl = document.getElementById("term");
  term.open(termEl);

  // O espelho TEM que usar a MESMA grade (cols×rows) do PTY de origem: o
  // Claude (TUI) redesenha por posição absoluta de cursor calculada pra
  // aquela geometria; grade diferente → linhas sobrepostas. Então em vez
  // de ajustar a GRADE ao overlay (o velho fit.fit()), fixamos a grade no
  // tamanho do PTY e ajustamos só a FONTE pra caber.
  let geom = { cols: Number("__COLS__") || 80, rows: Number("__ROWS__") || 24 };

  // Largura/altura de célula por 1px de fonte (monospace), medidas 1x.
  const _cell = (() => {
    const s = document.createElement("span");
    s.style.cssText =
      "position:absolute;visibility:hidden;white-space:pre;" +
      "font-family:monospace;line-height:1;font-size:100px";
    s.textContent = "0".repeat(50);
    document.body.appendChild(s);
    const r = s.getBoundingClientRect();
    s.remove();
    return { w: r.width / 50 / 100, h: r.height / 100 };
  })();

  function fitFont() {
    const availW = termEl.clientWidth - 8;
    const availH = termEl.clientHeight - 8;
    if (availW <= 0 || availH <= 0 || !geom.cols || !geom.rows) return;
    const pxW = availW / (geom.cols * _cell.w);
    const pxH = availH / (geom.rows * _cell.h);
    let px = Math.floor(Math.min(pxW, pxH));
    px = Math.max(6, Math.min(15, px));
    if (px !== term.options.fontSize) term.options.fontSize = px;
    // fontSize muda as métricas internas do xterm; re-fixa a grade do PTY.
    try { term.resize(geom.cols, geom.rows); } catch (e) {}
  }

  async function syncSize() {
    try {
      const r = await fetch(
        `/console/size?port=${active.port}&target=${active.target}&token=${TOKEN}`,
        { cache: "no-store" }
      );
      if (!r.ok) return;
      const s = await r.json();
      if (s.cols && s.rows && (s.cols !== geom.cols || s.rows !== geom.rows)) {
        geom = { cols: s.cols, rows: s.rows };
      }
    } catch (e) {}
    fitFont();
  }

  fitFont();
  window.addEventListener("resize", fitFont);
  setInterval(syncSize, 1500);

  function b64ToBytes(b64) {
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  let active = TABS[0];
  let es = null;

  function openStream() {
    if (es) { es.close(); es = null; }
    term.reset();
    // Cada aba (Claude / runner) tem seu PTY com geometria própria.
    syncSize();
    es = new EventSource(
      `/console/stream?port=${active.port}&target=${active.target}&token=${TOKEN}`
    );
    es.onmessage = (ev) => term.write(b64ToBytes(ev.data));
    es.onerror = () => {
      document.getElementById("off").style.display = "flex";
    };
    es.onopen = () => {
      document.getElementById("off").style.display = "none";
    };
  }

  const tabsEl = document.getElementById("tabs");
  const restartBtn = document.getElementById("restart");
  function renderTabs() {
    tabsEl.innerHTML = "";
    for (const t of TABS) {
      const el = document.createElement("span");
      el.className = "tab" + (t === active ? " active" : "");
      el.textContent = t.label;
      el.addEventListener("click", () => {
        active = t;
        renderTabs();
        openStream();
        term.focus();
      });
      tabsEl.appendChild(el);
    }
    // Reiniciar só faz sentido em aba de runner.
    restartBtn.style.display = active.target === "runner" ? "" : "none";
  }
  restartBtn.addEventListener("click", () => {
    fetch(`/runner/restart?port=${active.port}&token=${TOKEN}`).catch(() => {});
  });

  // Input só na aba do Claude — logs de runner são read-only aqui
  // (start/stop/restart ficam no app ou no botão ↻).
  term.onData((data) => {
    if (active.target !== "claude") return;
    fetch(`/console/input?port=${active.port}&token=${TOKEN}`, {
      method: "POST",
      headers: { "Content-Type": "text/plain;charset=UTF-8" },
      body: data,
    }).catch(() => {});
  });

  renderTabs();
  openStream();
  term.focus();
</script>
</body>
</html>
"""
