"""Poller assíncrono de git status pra exibir branch + contagem de
modificados na sidebar (junto de cada console).

Usa QThreadPool pra rodar `get_status` fora da UI thread, com cache TTL
por pasta pra evitar respawn em sucessão. Emite `status_ready(folder,
GitStatus)` quando há resultado novo (ou cache fresco) — o objeto
completo (ahead/behind/files) pra UI mostrar mais que branch+count.
"""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from .git_status import GitStatus, get_status

log = logging.getLogger(__name__)


class _RunnerSignals(QObject):
    done = Signal(str, object)  # folder, GitStatus | None


class _StatusRunner(QRunnable):
    def __init__(self, folder: str, signals: _RunnerSignals) -> None:
        super().__init__()
        self._folder = folder
        self._signals = signals

    def run(self) -> None:
        try:
            st = get_status(self._folder)
        except Exception:
            log.exception("repo status poller falhou em %s", self._folder)
            st = None
        self._signals.done.emit(self._folder, st)


class RepoStatusPoller(QObject):
    """Coleta git status por pasta com cache TTL e execução em pool."""

    # (folder, GitStatus). status.is_repo=False quando não é repo git.
    status_ready = Signal(str, object)

    def __init__(self, ttl_seconds: float = 4.0, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ttl = ttl_seconds
        self._pool = QThreadPool()
        # 2 threads basta — rodar mais não acelera (subprocess+disk-bound) e
        # ainda pode brigar com outros pollers (git_panel) por locks do repo.
        self._pool.setMaxThreadCount(2)
        self._signals = _RunnerSignals()
        self._signals.done.connect(self._on_done)
        self._inflight: set[str] = set()
        # folder -> (timestamp, GitStatus)
        self._cache: dict[str, tuple[float, GitStatus]] = {}

    def request(self, folder: str) -> None:
        """Pede status pra `folder`. Se houver entry fresca no cache,
        emite na hora (síncrono). Caso contrário, agenda fetch e emite
        depois pelo signal.
        """
        if not folder:
            return
        now = time.monotonic()
        cached = self._cache.get(folder)
        if cached and (now - cached[0]) < self._ttl:
            self.status_ready.emit(folder, cached[1])
            return
        # Mesmo com cache stale, emite o valor antigo enquanto a fetch
        # roda — evita flicker do label sumindo e reaparecendo.
        if cached:
            self.status_ready.emit(folder, cached[1])
        if folder in self._inflight:
            return
        self._inflight.add(folder)
        self._pool.start(_StatusRunner(folder, self._signals))

    def invalidate(self, folder: str) -> None:
        self._cache.pop(folder, None)

    def _on_done(self, folder: str, status: GitStatus | None) -> None:
        self._inflight.discard(folder)
        now = time.monotonic()
        if status is None or not status.is_repo:
            # GitStatus sintético mantém o contrato "branch vazia esconde
            # o chip" sem caller precisar tratar None.
            status = GitStatus(folder=folder, is_repo=False)
        self._cache[folder] = (now, status)
        self.status_ready.emit(folder, status)
