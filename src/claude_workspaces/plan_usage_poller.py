"""Poller assíncrono do status de uso do plano (label da sidebar).

Antes isso rodava inline no tick de 5s da MainWindow: `fetch_plan_usage`
fazia um urlopen síncrono (timeout 8s) na UI thread a cada expiração do
TTL/clique no ⟳, e o fallback USD-baseado varria ~/.claude/projects
inteiro no main thread. Aqui tudo roda num QThreadPool de 1 thread
(single-flight), no padrão do repo_status_poller, e o resultado volta
pronto pra renderizar via signal.

Frescor: o min-interval só espaça os RECÁLCULOS; os dados em si nunca vêm
de TTL cego — usage_telemetry invalida seus caches por (mtime, size,
inode) dos arquivos, então cada recálculo reflete o disco daquele momento.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

log = logging.getLogger(__name__)

# O label é decorativo (% de uso do plano) — recalcular a cada tick de 5s
# era desperdício; 30s mantém a sensação de "ao vivo" sem custo. O ⟳
# (force) ignora o intervalo, nunca o single-flight.
MIN_INTERVAL_SECONDS = 30.0


@dataclass
class PlanUsageResult:
    """Tudo que o render do label precisa, já computado fora da UI thread."""

    backend: str = "claude"
    snap: object | None = None  # PlanUsageSnapshot | None (API oficial)
    cooldown_seconds: int = 0
    # Fallback USD-baseado (só preenchido quando a API não respondeu e não
    # há cooldown — exatamente o caso em que o render vai exibi-lo).
    fallback_window: object | None = None  # PlanUsageWindow | None
    fallback_weekly: object | None = None  # WeeklyPlanUsage | None
    # Agregados do OpenCode (backend opencode) — dict cwd → UsageStats.
    opencode_recent: dict = field(default_factory=dict)
    opencode_weekly: dict = field(default_factory=dict)


class _Signals(QObject):
    done = Signal(object)  # PlanUsageResult


class _Runner(QRunnable):
    def __init__(self, backend: str, force: bool, signals: _Signals) -> None:
        super().__init__()
        self._backend = backend
        self._force = force
        self._signals = signals

    def run(self) -> None:
        result = PlanUsageResult(backend=self._backend)
        try:
            self._collect(result)
        except Exception:
            log.exception("plan usage poller falhou")
        self._signals.done.emit(result)

    def _collect(self, result: PlanUsageResult) -> None:
        from datetime import UTC, datetime, timedelta

        from .plan_usage_api import cooldown_remaining_seconds, fetch_plan_usage
        from .usage_telemetry import aggregate_usage_opencode, local_plan_usage

        if self._backend == "opencode":
            now = datetime.now(UTC)
            try:
                result.opencode_recent = aggregate_usage_opencode(
                    now - timedelta(hours=5)
                )
                result.opencode_weekly = aggregate_usage_opencode(
                    now - timedelta(days=7)
                )
            except Exception:  # noqa: BLE001
                log.debug("falha ao agregar uso do OpenCode", exc_info=True)

        try:
            result.snap = fetch_plan_usage(force=self._force)
        except Exception:  # noqa: BLE001
            log.debug("fetch_plan_usage falhou", exc_info=True)
        result.cooldown_seconds = cooldown_remaining_seconds()

        snap = result.snap
        has_api = snap is not None and (
            getattr(snap, "five_hour", None) is not None
            or getattr(snap, "seven_day", None) is not None
            or getattr(snap, "seven_day_sonnet", None) is not None
        )
        if not has_api and result.cooldown_seconds <= 0:
            # Fallback USD-baseado a partir dos JSONLs locais — só computa
            # quando vai ser exibido (API sem dados e sem cooldown).
            try:
                result.fallback_window, result.fallback_weekly = local_plan_usage()
            except Exception:  # noqa: BLE001
                log.debug("falha ao agregar uso do plano", exc_info=True)


class PlanUsagePoller(QObject):
    """Recalcula o uso do plano em background, no máximo a cada
    MIN_INTERVAL_SECONDS (force ignora o intervalo)."""

    done = Signal(object)  # PlanUsageResult

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._signals = _Signals()
        self._signals.done.connect(self._on_done)
        self._inflight = False
        self._last_done = 0.0

    def request(self, backend: str, force: bool = False) -> None:
        if self._inflight:
            return
        now = time.monotonic()
        if not force and (now - self._last_done) < MIN_INTERVAL_SECONDS:
            return
        self._inflight = True
        self._pool.start(_Runner(backend, force, self._signals))

    def _on_done(self, result: object) -> None:
        self._inflight = False
        self._last_done = time.monotonic()
        self.done.emit(result)
