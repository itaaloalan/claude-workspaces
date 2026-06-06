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

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger(__name__)

DEFAULT_PORT = 43210


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

    # ---- ciclo de vida -----------------------------------------------------

    def start(self) -> bool:
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 (API do http.server)
                path = self.path.split("?")[0]
                if path == "/state.json":
                    body = json.dumps(
                        outer._payload(), ensure_ascii=False
                    ).encode("utf-8")
                    self.send_response(200)
                    self.send_header(
                        "Content-Type", "application/json; charset=utf-8"
                    )
                    # Extensão/content scripts buscam de origens localhost
                    # variadas — CORS liberado (read-only e local).
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if path == "/open":
                    ok = outer._open_folder(self.path)
                    self.send_response(204 if ok else 404)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    return
                if path == "/focus":
                    ok = outer._request_focus(self.path)
                    self.send_response(204 if ok else 404)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
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
        log.info("StateServer em http://%s:%d/state.json", self._host, self._port)
        return True

    def stop(self) -> None:
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                log.debug("shutdown do StateServer falhou", exc_info=True)
            self._httpd = None

    @property
    def running(self) -> bool:
        return self._httpd is not None

    # ---- dados ---------------------------------------------------------------

    def update(self, snapshot: dict) -> None:
        """Snapshot {"ports": {"4202": {workspace, runner, scope, cwd,
        status...}}} — empurrado pela UI thread (sem git aqui)."""
        with self._lock:
            self._snapshot = snapshot

    def _payload(self) -> dict:
        with self._lock:
            snap = json.loads(json.dumps(self._snapshot))  # deep copy barato
        for entry in snap.get("ports", {}).values():
            cwd = entry.get("cwd") or ""
            if cwd:
                entry.update(self._branch_info(cwd))
        snap["ts"] = time.time()
        return snap

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
        info = {"branch": "", "worktree": False}
        try:
            from ..git_worktree import current_branch, is_worktree_path
            info["worktree"] = bool(is_worktree_path(cwd))
            info["branch"] = current_branch(cwd) or ""
        except Exception:
            log.debug("branch_info falhou pra %s", cwd, exc_info=True)
        with self._lock:
            self._branch_cache[cwd] = (now + 5.0, info)
        return info
