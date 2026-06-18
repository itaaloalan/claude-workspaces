"""Testes do ProcessMonitor — amostragem da árvore e faxina de memória."""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from claude_workspaces.process_monitor import (
    CAT_APP,
    CAT_RUNNER,
    CAT_WEBENGINE,
    ProcessMonitor,
    human_bytes,
)


def test_human_bytes_units():
    assert human_bytes(0) == "0 B"
    assert human_bytes(512) == "512 B"
    assert human_bytes(1536) == "1.5 KB"
    assert human_bytes(5 * 1024 * 1024) == "5.0 MB"
    assert human_bytes(2 * 1024 ** 3) == "2.0 GB"


def test_human_bytes_negative_clamped():
    assert human_bytes(-100) == "0 B"


def test_sample_includes_self():
    """O snapshot da árvore do próprio processo conta ao menos 1 processo e
    algum RSS, e cai no grupo App quando não há leaders."""
    mon = ProcessMonitor()
    snap = mon.sample({})
    assert snap.n_procs >= 1
    assert snap.total_rss > 0
    assert any(g.category == CAT_APP for g in snap.groups)
    # Grupos vêm ordenados por RSS desc.
    rss = [g.rss for g in snap.groups]
    assert rss == sorted(rss, reverse=True)


def test_sample_attributes_child_to_leader():
    """Um processo filho vira um grupo próprio quando seu pid é um leader."""
    child = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", "import time; time.sleep(5)"]
    )
    try:
        time.sleep(0.2)
        mon = ProcessMonitor()
        leaders = {child.pid: (CAT_RUNNER, "Runner teste")}
        snap = mon.sample(leaders)
        runner_groups = [g for g in snap.groups if g.category == CAT_RUNNER]
        assert len(runner_groups) == 1
        g = runner_groups[0]
        assert g.pid == child.pid
        assert g.label == "Runner teste"
        assert g.rss > 0
        assert g.stoppable  # runner é encerrável
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_console_group_not_stoppable():
    from claude_workspaces.process_monitor import CAT_CONSOLE

    child = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", "import time; time.sleep(5)"]
    )
    try:
        time.sleep(0.2)
        mon = ProcessMonitor()
        snap = mon.sample({child.pid: (CAT_CONSOLE, "Console x")})
        groups = [g for g in snap.groups if g.category == CAT_CONSOLE]
        assert len(groups) == 1
        assert not groups[0].stoppable  # console aparece mas não é morto daqui
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_cpu_percent_is_delta_between_samples():
    """1ª amostra de um pid novo dá 0% (prime); só faz sentido a partir da 2ª."""
    mon = ProcessMonitor()
    first = mon.sample({})
    # Soma de CPU pode ser 0 na primeira (objetos recém-primados).
    assert first.total_cpu >= 0.0
    time.sleep(0.05)
    second = mon.sample({})
    assert second.total_cpu >= 0.0


def test_free_memory_runs_and_reports():
    mon = ProcessMonitor()
    res = mon.free_memory()
    assert res.before_rss > 0
    assert res.after_rss > 0
    assert res.freed_rss >= 0
    assert res.reaped_zombies >= 0
    assert res.gc_collected >= 0


def test_free_memory_reaps_zombie_child():
    """Um filho direto que vira <defunct> é recolhido pela faxina."""
    pid = os.fork()
    if pid == 0:  # filho: sai imediatamente, vira zumbi até alguém dar wait
        os._exit(0)
    time.sleep(0.2)
    mon = ProcessMonitor()  # root_pid == os.getpid()
    res = mon.free_memory()
    assert res.reaped_zombies >= 1
    # Não deve sobrar pra reapear de novo.
    with pytest.raises(ChildProcessError):
        os.waitpid(pid, 0)


def test_sample_empty_when_root_missing():
    mon = ProcessMonitor(root_pid=999_999_999)  # pid improvável
    snap = mon.sample({})
    assert snap.n_procs == 0
    assert snap.total_rss == 0
    assert snap.groups == []


def test_webengine_category_by_name(monkeypatch):
    """Processo cujo nome contém 'QtWebEngine' cai no grupo navegador."""

    class FakeProc:
        def __init__(self, pid, ppid, name, rss):
            self.pid = pid
            self._ppid = ppid
            self._name = name
            self._rss = rss

        def ppid(self):
            return self._ppid

        def oneshot(self):
            from contextlib import nullcontext
            return nullcontext()

        def memory_info(self):
            from types import SimpleNamespace
            return SimpleNamespace(rss=self._rss)

        def name(self):
            return self._name

        def cmdline(self):
            return [self._name]

        def status(self):
            return "running"

        def cpu_percent(self, _=None):
            return 0.0

        def children(self, recursive=False):
            return []

    root = FakeProc(1000, 1, "claude-workspaces", 100)
    helper = FakeProc(1001, 1000, "QtWebEngineProcess", 200)

    mon = ProcessMonitor.__new__(ProcessMonitor)
    mon.root_pid = 1000
    mon._cpu_cache = {}
    monkeypatch.setattr(mon, "_tree", lambda: [root, helper])

    snap = mon.sample({})
    cats = {g.category for g in snap.groups}
    assert CAT_WEBENGINE in cats
    assert CAT_APP in cats
    web = next(g for g in snap.groups if g.category == CAT_WEBENGINE)
    assert web.rss == 200
    assert not web.stoppable
