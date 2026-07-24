"""Coalescing de output do TerminalBridge (fix de perf do renderer).

Cada read de PTY (≤8KB) virava uma mensagem QWebChannel própria — sob TUI
redesenhando, rajada contínua de IPCs pequenas mantinha o renderer em churn
permanente de heap. O bridge agora acumula e descarrega 1x por janela de
16ms (ou imediatamente ao passar de _FLUSH_MAX). Estes testes fixam ordem,
latência e os caminhos de reset (go_live/suspend_live/replay_filtered).
"""
from __future__ import annotations

import time

from claude_workspaces.pty_session import PtySession
from claude_workspaces.ui.terminal_widget import TerminalBridge


def _make_bridge() -> tuple[TerminalBridge, list[bytes]]:
    bridge = TerminalBridge(PtySession())
    bridge._live = True
    emitted: list[bytes] = []
    bridge.output_to_terminal.connect(lambda b: emitted.append(bytes(b)))
    return bridge, emitted


def _pump_until(qapp, cond, timeout_s: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not cond() and time.monotonic() < deadline:
        qapp.processEvents()


def test_chunks_coalesce_into_single_emit(qapp):
    bridge, emitted = _make_bridge()
    bridge._on_pty_output(b"um ")
    bridge._on_pty_output(b"dois ")
    bridge._on_pty_output(b"tres")
    # Nada inline — tudo espera o flush do timer.
    assert emitted == []
    _pump_until(qapp, lambda: emitted)
    assert emitted == [b"um dois tres"]


def test_flush_max_forces_immediate_emit(qapp):
    bridge, emitted = _make_bridge()
    big = b"x" * TerminalBridge._FLUSH_MAX
    bridge._on_pty_output(big)
    # Acima do teto: flush síncrono, sem esperar o timer.
    assert emitted == [big]


def test_emit_direct_flushes_pending_first_preserving_order(qapp):
    bridge, emitted = _make_bridge()
    bridge._on_pty_output(b"log do processo\n")
    bridge.emit_direct(b"[banner]\n")
    # O pendente sai ANTES do banner — ordem do stream preservada.
    assert emitted == [b"log do processo\n", b"[banner]\n"]


def test_suspend_live_discards_pending(qapp):
    bridge, emitted = _make_bridge()
    bridge._on_pty_output(b"vai ser descartado")
    bridge.suspend_live()
    assert bridge._live is False
    _pump_until(qapp, lambda: emitted, timeout_s=0.1)
    assert emitted == []
    # Output com o gate fechado também não enfileira nada.
    bridge._on_pty_output(b"gated")
    assert not bridge._out_buf


def test_go_live_drops_stale_pending_before_replay(qapp):
    bridge, emitted = _make_bridge()
    bridge._on_pty_output(b"lixo pre-reload")
    cleared: list[bool] = []
    bridge.clear_requested.connect(lambda: cleared.append(True))
    bridge.go_live(b"historico")
    # O replay é direto e nada do coalescido antigo vaza após o reset.
    assert cleared and emitted == [b"historico"]
    _pump_until(qapp, lambda: len(emitted) > 1, timeout_s=0.1)
    assert emitted == [b"historico"]


def test_filtered_path_still_filters_by_line(qapp):
    bridge, emitted = _make_bridge()
    bridge.set_filter("error")
    bridge._on_pty_output(b"linha ok\nerror: boom\noutra\n")
    _pump_until(qapp, lambda: emitted)
    assert emitted == [b"error: boom\n"]
