"""Watchdog de stalls do main thread — nomeia qualquer freeze da UI.

A instrumentação pontual (`perf.timed`) só mede o que alguém lembrou de
envolver. Este watchdog pega o resto: um heartbeat (QTimer de 50ms) atualiza
um timestamp no main thread; uma thread daemon confere o timestamp e, quando
o main thread fica >200ms sem bater (event loop bloqueado), captura o stack
dele via `sys._current_frames()` — apontando exatamente ONDE travou — espera
o heartbeat voltar pra medir a duração real e loga:

    [STALL] main thread bloqueado ~412ms
    stack no momento do stall:
      File "...", line N, in ...

Todo stall alimenta `perf.record("ui.stall_ms", dur)`, então o perf.log
mostra n/avg/max de travadas por janela de 30s mesmo quando o stack é
suprimido pelo throttle (máx. 1 stack a cada 5s — um loop de stalls não
pode virar o próprio spam).

Ligado junto de `settings.perf_logging_enabled`, instalado por `install()`
em app.main() DEPOIS de `window.show()` — o boot inteiro não conta como
stall. Custo em regime: um QTimer de 50ms + uma thread dormindo.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
import traceback

from PySide6.QtCore import QObject, QTimer

log = logging.getLogger(__name__)

# Acima disso o event loop é considerado travado. 200ms é perceptível como
# engasgo de animação/clique, mas alto o bastante pra ignorar GC/paint pesado.
STALL_THRESHOLD_S = 0.200
# Loga stack no máximo a cada tanto — os demais stalls só contam no perf.log.
_STACK_LOG_INTERVAL_S = 5.0
_HEARTBEAT_MS = 50
_STACK_LIMIT = 12  # frames mais internos mostrados


class StallWatchdog(QObject):
    """Instale com `install()`; pare com `stop()` (testes)."""

    def __init__(
        self,
        *,
        threshold_s: float = STALL_THRESHOLD_S,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._threshold = float(threshold_s)
        self._last_beat = time.monotonic()
        self._main_tid = threading.get_ident()
        self._stop = threading.Event()
        self._last_stack_log = 0.0
        self._suppressed = 0
        self._timer = QTimer(self)
        self._timer.setInterval(_HEARTBEAT_MS)
        self._timer.timeout.connect(self._beat)
        self._timer.start()
        self._thread = threading.Thread(
            target=self._watch, name="stall-watchdog", daemon=True
        )
        self._thread.start()

    # ---- main thread ----
    def _beat(self) -> None:
        self._last_beat = time.monotonic()

    def stop(self) -> None:
        self._stop.set()
        self._timer.stop()

    # ---- watchdog thread ----
    def _watch(self) -> None:
        from . import perf
        while not self._stop.wait(_HEARTBEAT_MS / 1000):
            now = time.monotonic()
            beat = self._last_beat
            if (now - beat) < self._threshold:
                continue
            # Main thread está travado AGORA — captura o stack no ato.
            stack = self._grab_main_stack()
            # Espera o heartbeat voltar pra medir a duração total do stall
            # (cap de 30s: se nunca volta, loga o que tem e segue).
            deadline = now + 30.0
            while (
                self._last_beat == beat
                and time.monotonic() < deadline
                and not self._stop.is_set()
            ):
                time.sleep(_HEARTBEAT_MS / 1000)
            dur_ms = (time.monotonic() - beat) * 1000
            perf.record("ui.stall_ms", dur_ms)
            self._log_stall(dur_ms, stack)

    def _grab_main_stack(self) -> str:
        try:
            frame = sys._current_frames().get(self._main_tid)
            if frame is None:
                return "(stack indisponível)"
            return "".join(traceback.format_stack(frame, limit=_STACK_LIMIT))
        except Exception:  # noqa: BLE001 — diagnóstico nunca derruba nada
            return "(falha capturando stack)"

    def _log_stall(self, dur_ms: float, stack: str) -> None:
        now = time.monotonic()
        if (now - self._last_stack_log) < _STACK_LOG_INTERVAL_S:
            self._suppressed += 1
            return
        self._last_stack_log = now
        suffix = ""
        if self._suppressed:
            suffix = f" ({self._suppressed} stall(s) anteriores sem stack — ver ui.stall_ms no perf.log)"
            self._suppressed = 0
        level = logging.WARNING if dur_ms >= 1000 else logging.INFO
        log.log(
            level,
            "[STALL] main thread bloqueado ~%.0fms%s\nstack no momento do stall:\n%s",
            dur_ms, suffix, stack,
        )


_instance: StallWatchdog | None = None


def install(*, threshold_s: float = STALL_THRESHOLD_S) -> StallWatchdog | None:
    """Cria o watchdog global (idempotente). Chamar no main thread, com o
    event loop já rodando (depois de window.show())."""
    global _instance
    if _instance is None:
        _instance = StallWatchdog(threshold_s=threshold_s)
        log.info(
            "StallWatchdog ativo (threshold=%.0fms, heartbeat=%dms)",
            threshold_s * 1000, _HEARTBEAT_MS,
        )
    return _instance


__all__ = ["STALL_THRESHOLD_S", "StallWatchdog", "install"]
