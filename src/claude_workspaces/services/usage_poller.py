"""Poller assíncrono de `usage_for_session` (modelo + tokens da sessão
Claude exibidos na sidebar de cada console).

Antes disso, `MainWindow._refresh_terminal_git_info` chamava
`usage_for_session` direto no tick de 8s, na UI thread. O cache incremental
de `usage_telemetry` deixa o regime barato (só parseia bytes novos do
JSONL), mas o PRIMEIRO parse de uma sessão grande — ou um append grande
após um turno longo/compaction — ainda percorre o arquivo inteiro; nos logs
de produção isso apareceu como stalls de main thread de 500ms a 5s. Aqui o
parse roda num QThreadPool de 1 thread (padrão de `repo_status_poller.py` /
`plan_usage_poller.py`) e o resultado volta pronto via signal.

Sem TTL: `usage_for_session` já invalida por (size, mtime_ns, inode) do
arquivo, então cada request reflete o disco atual. O guard `_inflight` por
tab_id só evita empilhar 2 jobs pra mesma aba entre um tick e outro."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

log = logging.getLogger(__name__)


class _JobSignals(QObject):
    done = Signal(object, object)  # tab_id, UsageStats | None


class _UsageJob(QRunnable):
    def __init__(self, tab_id: object, session_path: Path, signals: _JobSignals) -> None:
        super().__init__()
        self._tab_id = tab_id
        self._session_path = session_path
        self._signals = signals

    def run(self) -> None:
        from ..usage_telemetry import usage_for_session

        stats = None
        try:
            stats = usage_for_session(self._session_path)
        except Exception:
            log.debug("usage poller falhou em %s", self._session_path, exc_info=True)
        self._signals.done.emit(self._tab_id, stats)


class UsagePoller(QObject):
    """`request(tab_id, session_path)` agenda o parse fora da UI thread;
    `usage_ready(tab_id, UsageStats)` entrega o resultado no main thread."""

    usage_ready = Signal(object, object)  # tab_id, UsageStats

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._signals = _JobSignals()
        self._signals.done.connect(self._on_done)
        self._inflight: set[object] = set()

    def request(self, tab_id: object, session_path: Path) -> None:
        if tab_id in self._inflight:
            return
        self._inflight.add(tab_id)
        self._pool.start(_UsageJob(tab_id, session_path, self._signals))

    def _on_done(self, tab_id: object, stats: object | None) -> None:
        self._inflight.discard(tab_id)
        if stats is not None:
            self.usage_ready.emit(tab_id, stats)


__all__ = ["UsagePoller"]
