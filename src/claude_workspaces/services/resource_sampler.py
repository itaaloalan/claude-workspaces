"""ResourceSampler — amostragem de RAM/CPU fora da UI thread.

O walk do psutil (`ProcessMonitor.sample_totals`) custa ~10ms com poucas
dezenas de processos e cresce com a árvore (WebEngine + consoles claude).
Rodava direto no tick do `_resource_timer` na UI thread — 10ms de jank a
cada 8s, visível como micro-engasgo em animações/scroll. Aqui o walk roda
num QThreadPool de 1 thread e o resultado volta pro main thread via signal
(conexão queued automática).

Guard `_inflight` garante no máximo uma amostra em voo — o `ProcessMonitor`
não é thread-safe (cache de objetos psutil pro delta de %CPU), então nunca
há duas amostras concorrentes por este caminho. O gerenciador de recursos
aberto continua amostrando sincronamente no main thread, mas nesse estado o
timer de fundo fica pausado (ver `_open_resource_dialog`).
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

log = logging.getLogger(__name__)


class _JobSignals(QObject):
    done = Signal(object)  # Snapshot | None


class _SampleJob(QRunnable):
    def __init__(self, monitor, signals: _JobSignals) -> None:
        super().__init__()
        self._monitor = monitor
        self._signals = signals

    def run(self) -> None:
        from .. import perf
        try:
            with perf.timed("resources.sample_totals"):
                snap = self._monitor.sample_totals()
        except Exception:  # noqa: BLE001 — monitor nunca pode derrubar nada
            log.exception("falha amostrando recursos")
            snap = None
        self._signals.done.emit(snap)


class ResourceSampler(QObject):
    """Fachada: `request()` agenda uma amostra; `sample_ready` entrega o
    Snapshot no main thread. Requests com amostra em voo são ignorados."""

    sample_ready = Signal(object)  # Snapshot

    def __init__(self, monitor, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._monitor = monitor
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._signals = _JobSignals()
        self._signals.done.connect(self._on_done)
        self._inflight = False

    def request(self) -> None:
        if self._inflight:
            return
        self._inflight = True
        self._pool.start(_SampleJob(self._monitor, self._signals))

    def _on_done(self, snap: object) -> None:
        self._inflight = False
        if snap is not None:
            self.sample_ready.emit(snap)


__all__ = ["ResourceSampler"]
