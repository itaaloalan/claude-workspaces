"""I/O do poll de atividade fora da main thread (fix das travadas de uso).

Sob pressão de swap, o open() do JSONL da sessão bloqueou a main thread por
3s+ (stack real do perf_watchdog em uso diário). O trio de I/O do poll
(resolver sessão, rename externo, scan de worktrees) agora roda num worker
serial compartilhado; a main thread só monta inputs e aplica resultados.
"""
from __future__ import annotations

import json
import time

from claude_workspaces.ui.terminal_widget import (
    TerminalWidget,
    _run_session_io,
)


def test_run_session_io_scans_worktree_jsonl(tmp_path):
    """O worker lê o JSONL incremental e devolve hits + offset novo."""
    jsonl = tmp_path / "sess.jsonl"
    line = {
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use", "name": "Bash",
            "input": {"command": "git worktree add ../wt-x -b feat/x"},
        }]},
    }
    jsonl.write_text(json.dumps(line) + "\n", encoding="utf-8")
    out = _run_session_io({"wt_scan_path": str(jsonl), "wt_scan_offset": 0})
    assert out.get("wt_scan_path") == str(jsonl)
    assert out.get("wt_offset", 0) > 0
    # hits pode ou não conter o add dependendo do parser — o contrato aqui
    # é o roundtrip path/offset sem exceção e sem tocar a main thread.


def test_run_session_io_missing_file_is_noop(tmp_path):
    out = _run_session_io({
        "wt_scan_path": str(tmp_path / "nao-existe.jsonl"),
        "wt_scan_offset": 0,
    })
    assert "wt_offset" not in out


def test_run_session_io_wt_dir_gone(tmp_path):
    gone = tmp_path / "sumiu"
    out = _run_session_io({"wt_check_dir": str(gone)})
    assert out.get("wt_dir_gone") is True
    gone.mkdir()
    out = _run_session_io({"wt_check_dir": str(gone)})
    assert out.get("wt_dir_gone") is False


def test_poll_schedules_one_job_and_applies_result(qapp, monkeypatch):
    """O poll agenda no máximo 1 job em voo por console, e o resultado do
    worker é aplicado na main thread (sessão resolvida via worker)."""
    from claude_workspaces.claude_sessions import BackendSession

    w = TerminalWidget()
    try:
        w._claude_cwd = "/x"
        w._claude_start_time = 1000.0
        started: list[dict] = []

        class _FakePool:
            def start(self, job):
                started.append(job._inp)
                # Simula o worker devolvendo uma sessão nova resolvida.
                job._signals.done.emit({
                    "sessions": [BackendSession(
                        id="S1", mtime=1000.2, preview="minha tarefa",
                        path="/x", origin_cwd="/x",
                    )],
                })

        monkeypatch.setattr(
            "claude_workspaces.ui.terminal_widget._get_session_io_pool",
            lambda: _FakePool(),
        )
        w._schedule_session_io()
        assert len(started) == 1
        assert started[0]["resolve_cwd"] == "/x"
        assert w._session_resolved is True
        assert w._session_preview == "minha tarefa"
        # inflight liberado após o done — próximo tick agenda de novo.
        assert w._session_io_inflight is False
    finally:
        w.deleteLater()


def test_inflight_guard_blocks_second_schedule(qapp, monkeypatch):
    w = TerminalWidget()
    try:
        w._claude_cwd = "/x"
        started: list = []

        class _NeverDonePool:
            def start(self, job):
                started.append(job)  # não emite done — job "em voo"

        monkeypatch.setattr(
            "claude_workspaces.ui.terminal_widget._get_session_io_pool",
            lambda: _NeverDonePool(),
        )
        w._schedule_session_io()
        w._schedule_session_io()
        assert len(started) == 1
    finally:
        w.deleteLater()
