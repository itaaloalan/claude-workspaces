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
# Multi-sampling durante o stall: re-captura o stack a cada tanto, até o
# teto — num stall longo, o perfil das amostras diz onde o tempo REALMENTE
# foi (a amostra única do início era cega pro resto).
_SAMPLE_EVERY_S = 2.0
_MAX_SAMPLES = 6


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
        self._last_beat_wall = time.time()
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
        self._last_beat_wall = time.time()

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
            samples: list[tuple[float, str]] = [(0.0, self._grab_main_stack())]
            beat_wall = self._last_beat_wall
            # Espera o heartbeat voltar pra medir a duração total do stall
            # (cap de 30s: se nunca volta, loga o que tem e segue).
            # Multi-sampling: re-amostra o stack a cada ~2s (máx. _MAX_SAMPLES)
            # — num stall de 24s, uma foto só do primeiro instante escondia
            # onde os outros 23s foram gastos (visto no freeze do restore de
            # boot: a amostra única caiu num addWidget inocente).
            deadline = now + 30.0
            last_sample = now
            while (
                self._last_beat == beat
                and time.monotonic() < deadline
                and not self._stop.is_set()
            ):
                time.sleep(_HEARTBEAT_MS / 1000)
                t = time.monotonic()
                if (
                    len(samples) < _MAX_SAMPLES
                    and t - last_sample >= _SAMPLE_EVERY_S
                ):
                    last_sample = t
                    samples.append((t - beat, self._grab_main_stack()))
            dur_ms = (time.monotonic() - beat) * 1000
            # CLOCK_MONOTONIC do Linux NÃO avança durante suspend/hibernate
            # (é isso que o distingue do CLOCK_BOOTTIME) — então dur_ms fica
            # pequeno mesmo que o notebook tenha ficado suspenso por horas.
            # O relógio de parede (time.time()), esse sim, salta o intervalo
            # inteiro. Um wall_dur_ms muito maior que dur_ms é justamente
            # esse descompasso: sinal de suspend, não de freeze real da UI.
            wall_dur_ms = (time.time() - beat_wall) * 1000
            if wall_dur_ms > dur_ms * 3 and wall_dur_ms > 5000:
                log.info(
                    "[STALL] ignorado (~%.0fms monotonic vs ~%.0fms parede — "
                    "provável suspend/hibernate, não freeze real)",
                    dur_ms, wall_dur_ms,
                )
                continue
            perf.record("ui.stall_ms", dur_ms)
            self._log_stall(dur_ms, samples)

    def _grab_main_stack(self) -> str:
        try:
            frame = sys._current_frames().get(self._main_tid)
            if frame is None:
                return "(stack indisponível)"
            return "".join(traceback.format_stack(frame, limit=_STACK_LIMIT))
        except Exception:  # noqa: BLE001 — diagnóstico nunca derruba nada
            return "(falha capturando stack)"

    def _log_stall(self, dur_ms: float, samples: list[tuple[float, str]]) -> None:
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
        if len(samples) == 1:
            body = f"stack no momento do stall:\n{samples[0][1]}"
        else:
            parts = [
                f"amostra {i + 1}/{len(samples)} @ ~{off:.1f}s:\n{stk}"
                for i, (off, stk) in enumerate(samples)
            ]
            body = "stacks amostrados durante o stall:\n" + "\n".join(parts)
        log.log(
            level,
            "[STALL] main thread bloqueado ~%.0fms%s\n%s",
            dur_ms, suffix, body,
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
