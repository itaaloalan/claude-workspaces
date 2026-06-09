"""Regressão: o log ao vivo do runner tem que aparecer no console.

O lazy-load do console (1.0.3) adicionou um gate `_live` ao TerminalBridge
(nasce desligado; quem liga é go_live()). O TerminalWidget chama go_live ao
abrir, mas o RunnerWidget — que tem view eager — ficou sem destravar, então
todo output ao vivo do PTY era descartado e só os emits diretos (banner)
apareciam. Este teste fixa que o frontend ficando pronto destrava o gate e
replaya o buffer.
"""

from claude_workspaces.models import RunnerConfig
from claude_workspaces.ui.runner_widget import RunnerWidget


def test_bridge_ready_goes_live_and_replays(qapp):
    w = RunnerWidget(RunnerConfig(name="glassfish-ogpms", start_cmd="echo hi"),
                     default_cwd="/tmp")
    try:
        # Antes do frontend carregar: gate fechado (output ao vivo descartado).
        assert w.bridge._live is False

        emitted: list[bytes] = []
        w.bridge.output_to_terminal.connect(lambda b: emitted.append(bytes(b)))
        w._log_buf = "linha-de-log\n"

        # Simula o xterm.js do runner sinalizando que ficou pronto.
        w._on_bridge_ready()

        # Gate destravado + replay do que estava bufferizado no _log_buf.
        assert w.bridge._live is True
        assert any(b"linha-de-log" in e for e in emitted)
    finally:
        w.terminate()
        w.deleteLater()


def test_live_pty_output_passes_after_ready(qapp):
    """Depois de ready, um chunk do PTY chega ao terminal (não fica gated)."""
    w = RunnerWidget(RunnerConfig(name="ogpms-xhtml-watch", start_cmd="echo hi"),
                     default_cwd="/tmp")
    try:
        w._on_bridge_ready()
        emitted: list[bytes] = []
        w.bridge.output_to_terminal.connect(lambda b: emitted.append(bytes(b)))
        # Chunk como se viesse do PTY (passa pelo _on_pty_output do bridge).
        w.session.output_received.emit(b"compilando xhtml...\n")
        assert any(b"compilando xhtml" in e for e in emitted)
    finally:
        w.terminate()
        w.deleteLater()
