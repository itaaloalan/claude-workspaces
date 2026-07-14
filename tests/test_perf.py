"""Testes de `perf.flush()` — cada métrica deve virar uma linha de log
independente (não um bloco multi-linha), pra ficar `grep`ável por hora sem
parser dedicado."""
from __future__ import annotations

import logging

import pytest

from claude_workspaces import perf


@pytest.fixture(autouse=True)
def _reset_perf(monkeypatch):
    monkeypatch.setattr(perf, "_enabled", True)
    monkeypatch.setattr(perf, "_timers", {})
    monkeypatch.setattr(perf, "_counters", {})
    monkeypatch.setattr(perf, "_window_start", __import__("time").monotonic())
    yield


def test_flush_emits_one_record_per_metric(caplog):
    caplog.set_level(logging.INFO, logger="perf")
    perf.record("git.status.subprocess", 12.5)
    perf.record("git.status.subprocess", 30.0)
    perf.count("pty.bytes", 100)

    perf.flush()

    messages = [r.message for r in caplog.records if r.name == "perf"]
    # 1 linha de header "=== janela ==="  + 1 por timer + 1 por contador.
    assert len(messages) == 3
    assert messages[0].startswith("=== janela")
    timer_line = next(m for m in messages if m.startswith("T "))
    assert "git.status.subprocess" in timer_line
    assert "n=2" in timer_line
    counter_line = next(m for m in messages if m.startswith("C "))
    assert "pty.bytes" in counter_line
    assert "total=" in counter_line


def test_flush_noop_when_disabled(caplog, monkeypatch):
    monkeypatch.setattr(perf, "_enabled", False)
    caplog.set_level(logging.INFO, logger="perf")
    perf.record("x", 1.0)  # também é no-op quando desligado
    perf.flush()
    assert [r for r in caplog.records if r.name == "perf"] == []


def test_flush_noop_when_no_data(caplog):
    caplog.set_level(logging.INFO, logger="perf")
    perf.flush()
    assert [r for r in caplog.records if r.name == "perf"] == []
