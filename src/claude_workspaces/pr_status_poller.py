"""Poller assíncrono de PR/MR aberto pra cada console da sidebar.

Segue o mesmo padrão do RepoStatusPoller: cache TTL + QThreadPool.
TTL maior (60s) porque PRs mudam bem menos que branch+modified.

Emite `pr_ready(folder, pr)` — `pr` é um ExistingPR (url, state, number,
draft) ou None quando não há PR/MR pra branch.
"""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from .pr_actions import ExistingPR, find_existing_pr_or_mr

log = logging.getLogger(__name__)


class _PrRunnerSignals(QObject):
    done = Signal(str, str, object)  # folder, branch, ExistingPR | None


class _PrRunner(QRunnable):
    def __init__(self, folder: str, branch: str, signals: _PrRunnerSignals) -> None:
        super().__init__()
        self._folder = folder
        self._branch = branch
        self._signals = signals

    def run(self) -> None:
        pr: ExistingPR | None = None
        try:
            pr = find_existing_pr_or_mr(self._folder, self._branch)
        except Exception:
            log.debug("PR poller falhou em %s@%s", self._folder, self._branch, exc_info=True)
        self._signals.done.emit(self._folder, self._branch, pr)


class PrStatusPoller(QObject):
    """Consulta GitHub/GitLab pra PR/MR na branch atual de cada console."""

    # (folder, ExistingPR | None) — None quando não há PR/MR pra branch
    pr_ready = Signal(str, object)

    def __init__(self, ttl_seconds: float = 60.0, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ttl = ttl_seconds
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(2)
        self._signals = _PrRunnerSignals()
        self._signals.done.connect(self._on_done)
        self._inflight: set[tuple[str, str]] = set()
        # (folder, branch) -> (timestamp, ExistingPR | None)
        self._cache: dict[tuple[str, str], tuple[float, ExistingPR | None]] = {}

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

    def _on_done(self, folder: str, branch: str, pr: object) -> None:
        key = (folder, branch)
        self._inflight.discard(key)
        self._cache[key] = (time.monotonic(), pr)
        self.pr_ready.emit(folder, pr)
