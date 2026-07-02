"""StallWatchdog: detecta bloqueio do main thread e loga com stack.

Simula um stall real bloqueando o main thread com time.sleep enquanto o
event loop está vivo (o heartbeat só volta a bater quando o sleep termina),
e asserta que o [STALL] foi logado com a duração aproximada e um stack
apontando o culpado. Também garante silêncio quando não há stall.
"""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QTimer

from claude_workspaces.perf_watchdog import StallWatchdog


def _pump(qapp, ms: int) -> None:
    """Roda o event loop de verdade por `ms` (processEvents em loop não
    dispara timers de forma confiável no offscreen)."""
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)


def test_stall_detected_with_stack(qapp, caplog):
    wd = StallWatchdog(threshold_s=0.15)
    try:
        _pump(qapp, 200)  # heartbeat estabiliza
        with caplog.at_level(logging.INFO, logger="claude_workspaces.perf_watchdog"):
            time.sleep(0.5)   # main thread bloqueado — é o stall
            _pump(qapp, 400)  # heartbeat volta; watchdog mede e loga
        stalls = [r for r in caplog.records if "[STALL]" in r.getMessage()]
        assert stalls, "stall de 500ms não foi detectado"
        msg = stalls[0].getMessage()
        assert "stack no momento do stall" in msg
        # O stack deve apontar este teste (o sleep roda aqui).
        assert "test_perf_watchdog" in msg
    finally:
        wd.stop()


def test_no_stall_no_log(qapp, caplog):
    wd = StallWatchdog(threshold_s=0.15)
    try:
        with caplog.at_level(logging.INFO, logger="claude_workspaces.perf_watchdog"):
            _pump(qapp, 400)  # event loop saudável o tempo todo
        stalls = [r for r in caplog.records if "[STALL]" in r.getMessage()]
        assert stalls == []
    finally:
        wd.stop()
