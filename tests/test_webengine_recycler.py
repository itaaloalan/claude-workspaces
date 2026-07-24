"""WebEngineRecycler — watchdog que recicla o renderer inchado dos terminais.

Testa a máquina de estados com callbacks/pids fakes (sem QtWebEngine real):
limiar, amostras consecutivas, cooldown, morte do processo, fallback de
SIGKILL, pid alheio (view de PWA/diff) e a flag global recycling_active().
"""
from __future__ import annotations

import time

from claude_workspaces.process_monitor import RendererStat
from claude_workspaces.services import webengine_recycler as wr
from claude_workspaces.services.webengine_recycler import (
    WebEngineRecycler,
    recycling_active,
)

MB = 1024 * 1024


class _FakePage:
    def __init__(self, pid: int) -> None:
        self._pid = pid

    def renderProcessPid(self) -> int:  # noqa: N802 (API Qt)
        return self._pid


class _FakeView:
    def __init__(self, pid: int) -> None:
        self._page = _FakePage(pid)

    def page(self) -> _FakePage:
        return self._page


class _FakeWidget:
    def __init__(self, pid: int) -> None:
        self.view = _FakeView(pid)
        self.unloaded = 0

    def unload_view(self) -> None:
        self.unloaded += 1
        self.view = None


class _Harness:
    """Monta um recycler com mundo fake: widgets, pids vivos e kills."""

    def __init__(self, *, threshold_mb: int = 100, renderer_pid: int = 4242):
        self.renderer_pid = renderer_pid
        self.widgets = [_FakeWidget(renderer_pid), _FakeWidget(renderer_pid)]
        self.alive: set[int] = {renderer_pid}
        self.killed: list[int] = []
        self.reloads = 0
        self.recycler = WebEngineRecycler(
            threshold_bytes=lambda: threshold_mb * MB,
            collect_loaded=lambda: [w for w in self.widgets if w.view is not None],
            reload_active=self._reload,
            pid_alive=lambda p: p in self.alive,
            kill_pid=self._kill,
        )

    def _reload(self) -> None:
        self.reloads += 1

    def _kill(self, pid: int) -> None:
        self.killed.append(pid)
        self.alive.discard(pid)

    def sample(self, total_mb: int) -> None:
        self.recycler.on_sample(
            [RendererStat(pid=self.renderer_pid, rss=total_mb * MB, swap=0)]
        )


def _pump(qapp, cond, timeout_s: float = 3.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not cond() and time.monotonic() < deadline:
        qapp.processEvents()


def test_below_threshold_never_recycles(qapp):
    h = _Harness(threshold_mb=100)
    for _ in range(5):
        h.sample(50)
    assert all(w.unloaded == 0 for w in h.widgets)
    assert not recycling_active()


def test_single_spike_does_not_recycle(qapp):
    """Uma amostra acima do limiar (pico transitório) não dispara — só a
    OVER_SAMPLES-ésima consecutiva."""
    h = _Harness(threshold_mb=100)
    h.sample(200)
    assert all(w.unloaded == 0 for w in h.widgets)
    h.sample(50)  # voltou ao normal → contador zera
    h.sample(200)
    assert all(w.unloaded == 0 for w in h.widgets)


def test_two_over_samples_recycle_unload_wait_reload(qapp):
    h = _Harness(threshold_mb=100)
    h.sample(200)
    h.sample(200)
    # Disparou: todo widget carregado descarregado, ciclo ativo.
    assert all(w.unloaded == 1 for w in h.widgets)
    assert recycling_active()
    # Renderer morre sozinho (pages destruídas) → reload sem kill.
    h.alive.clear()
    _pump(qapp, lambda: h.reloads > 0)
    assert h.reloads == 1
    assert h.killed == []
    assert not recycling_active()


def test_stuck_renderer_gets_sigkill(qapp, monkeypatch):
    monkeypatch.setattr(WebEngineRecycler, "DEATH_TIMEOUT_MS", 300)
    h = _Harness(threshold_mb=100)
    h.sample(200)
    h.sample(200)
    # Renderer nunca morre sozinho → fallback SIGKILL após o timeout.
    _pump(qapp, lambda: h.reloads > 0)
    assert h.killed == [h.renderer_pid]
    assert h.reloads == 1
    assert not recycling_active()


def test_cooldown_blocks_consecutive_recycles(qapp):
    h = _Harness(threshold_mb=100)
    h.sample(200)
    h.sample(200)
    h.alive.clear()
    _pump(qapp, lambda: h.reloads == 1)
    # Renderer novo já nasce inchado (limiar baixo demais) — cooldown segura.
    h.widgets = [_FakeWidget(h.renderer_pid)]
    h.alive = {h.renderer_pid}
    for _ in range(4):
        h.sample(200)
    assert h.widgets[0].unloaded == 0
    assert h.reloads == 1


def test_foreign_renderer_pid_is_ignored(qapp):
    """Renderer inchado que NÃO hospeda views de terminal (PWA/diff viewer)
    não dispara recycle — descarregar terminais não liberaria nada."""
    h = _Harness(threshold_mb=100)
    h.recycler.on_sample(
        [RendererStat(pid=9999, rss=500 * MB, swap=0)]
    )
    h.recycler.on_sample(
        [RendererStat(pid=9999, rss=500 * MB, swap=0)]
    )
    assert all(w.unloaded == 0 for w in h.widgets)


def test_threshold_zero_disables(qapp):
    h = _Harness(threshold_mb=0)
    for _ in range(4):
        h.sample(10_000)
    assert all(w.unloaded == 0 for w in h.widgets)


def test_recycling_active_resets_on_finish(qapp):
    assert not recycling_active()
    h = _Harness(threshold_mb=100)
    assert h.recycler.recycle_now("teste manual")
    assert recycling_active()
    # Segundo recycle com um em andamento é rejeitado.
    assert not h.recycler.recycle_now("duplicado")
    h.alive.clear()
    _pump(qapp, lambda: not wr._recycling)
    assert not recycling_active()
    assert h.reloads == 1
