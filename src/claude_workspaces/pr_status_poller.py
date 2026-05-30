"""Poller assíncrono de PR/MR aberto pra cada console da sidebar.

Segue o mesmo padrão do RepoStatusPoller: cache TTL + QThreadPool.
TTL maior (60s) porque PRs mudam bem menos que branch+modified.

Emite `pr_ready(folder, pr_url)` — pr_url vazio quando não há PR aberto.
"""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from .pr_actions import find_existing_pr_or_mr

log = logging.getLogger(__name__)


class _PrRunnerSignals(QObject):
    done = Signal(str, str, str)  # folder, branch, pr_url (vazio = sem PR)


class _PrRunner(QRunnable):
    def __init__(self, folder: str, branch: str, signals: _PrRunnerSignals) -> None:
        super().__init__()
        self._folder = folder
        self._branch = branch
        self._signals = signals

    def run(self) -> None:
        pr_url = ""
        try:
            result = find_existing_pr_or_mr(self._folder, self._branch)
            if result:
                pr_url = result.url or ""
        except Exception:
            log.debug("PR poller falhou em %s@%s", self._folder, self._branch, exc_info=True)
        self._signals.done.emit(self._folder, self._branch, pr_url)


class PrStatusPoller(QObject):
    """Consulta GitHub/GitLab pra PR/MR aberto na branch atual de cada console."""

    # (folder, pr_url) — pr_url="" quando não há PR aberto
    pr_ready = Signal(str, str)

    def __init__(self, ttl_seconds: float = 60.0, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ttl = ttl_seconds
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(2)
        self._signals = _PrRunnerSignals()
        self._signals.done.connect(self._on_done)
        self._inflight: set[tuple[str, str]] = set()
        # (folder, branch) -> (timestamp, pr_url)
        self._cache: dict[tuple[str, str], tuple[float, str]] = {}

    def request(self, folder: str, branch: str) -> None:
        """Pede lookup de PR pra `folder`+`branch`. Emite do cache se fresco."""
        if not folder or not branch:
            return
        key = (folder, branch)
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and (now - cached[0]) < self._ttl:
            self.pr_ready.emit(folder, cached[1])
            return
        if cached:
            self.pr_ready.emit(folder, cached[1])
        if key in self._inflight:
            return
        self._inflight.add(key)
        self._pool.start(_PrRunner(folder, branch, self._signals))

    def invalidate(self, folder: str, branch: str = "") -> None:
        """Invalida cache para forçar re-consulta na próxima chamada."""
        if branch:
            self._cache.pop((folder, branch), None)
        else:
            for k in [k for k in self._cache if k[0] == folder]:
                self._cache.pop(k, None)

    def _on_done(self, folder: str, branch: str, pr_url: str) -> None:
        key = (folder, branch)
        self._inflight.discard(key)
        self._cache[key] = (time.monotonic(), pr_url)
        self.pr_ready.emit(folder, pr_url)
