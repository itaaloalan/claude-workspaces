"""Testes de services/runner_gen_history.py — dataclass + persistência JSON.

O arquivo de histórico é isolado via monkeypatch de `history_file()` para um
tmp_path, então não toca no ~/.config do usuário.
"""

import json

import pytest

from claude_workspaces.services import runner_gen_history as rgh
from claude_workspaces.services.runner_gen_history import RunnerGenEntry


@pytest.fixture
def hist_file(tmp_path, monkeypatch):
    f = tmp_path / "runner_gen_sessions.json"
    monkeypatch.setattr(rgh, "history_file", lambda: f)
    return f


def _entry(ws="ws-1", sid="sess-1", cwd="/tmp/p", hint="", created_at="2026-01-01"):
    return RunnerGenEntry(
        workspace_id=ws, session_id=sid, cwd=cwd, hint=hint, created_at=created_at
    )


# ---------- RunnerGenEntry ----------

def test_to_dict_from_dict_roundtrip():
    e = _entry(hint="subir web")
    e2 = RunnerGenEntry.from_dict(e.to_dict())
    assert e2 == e


def test_from_dict_coerces_missing_fields():
    e = RunnerGenEntry.from_dict({})
    assert e.workspace_id == ""
    assert e.session_id == ""
    assert e.cwd == ""
    assert e.is_valid() is False


def test_is_valid_requires_core_fields():
    assert _entry().is_valid() is True
    assert _entry(ws="").is_valid() is False
    assert _entry(sid="").is_valid() is False
    assert _entry(cwd="").is_valid() is False


# ---------- load_history ----------

def test_load_missing_file_is_empty(hist_file):
    assert rgh.load_history() == []


def test_load_corrupt_json_is_empty(hist_file):
    hist_file.write_text("{not json", encoding="utf-8")
    assert rgh.load_history() == []


def test_load_filters_invalid_entries(hist_file):
    payload = {
        "entries": [
            {"workspace_id": "w", "session_id": "s", "cwd": "/c"},
            {"workspace_id": "", "session_id": "", "cwd": ""},  # inválida
            "não-dict",  # ignorada
        ]
    }
    hist_file.write_text(json.dumps(payload), encoding="utf-8")
    out = rgh.load_history()
    assert len(out) == 1
    assert out[0].session_id == "s"


# ---------- add_entry ----------

def test_add_entry_persists(hist_file):
    rgh.add_entry(_entry(sid="a"))
    assert [e.session_id for e in rgh.load_history()] == ["a"]


def test_add_entry_dedups_by_session_id(hist_file):
    rgh.add_entry(_entry(sid="a", hint="v1"))
    rgh.add_entry(_entry(sid="a", hint="v2"))
    out = rgh.load_history()
    assert len(out) == 1
    assert out[0].hint == "v2"


def test_add_invalid_entry_is_noop(hist_file):
    rgh.add_entry(_entry(sid=""))
    assert rgh.load_history() == []


# ---------- remove_entry ----------

def test_remove_entry(hist_file):
    rgh.add_entry(_entry(sid="a"))
    rgh.add_entry(_entry(sid="b"))
    rgh.remove_entry("a")
    assert [e.session_id for e in rgh.load_history()] == ["b"]


def test_remove_unknown_is_noop(hist_file):
    rgh.add_entry(_entry(sid="a"))
    rgh.remove_entry("zzz")
    assert len(rgh.load_history()) == 1


def test_remove_empty_id_is_noop(hist_file):
    rgh.add_entry(_entry(sid="a"))
    rgh.remove_entry("")
    assert len(rgh.load_history()) == 1


# ---------- entries_for_workspace ----------

def test_entries_for_workspace_filters_and_sorts_desc(hist_file):
    rgh.add_entry(_entry(ws="w1", sid="old", created_at="2026-01-01"))
    rgh.add_entry(_entry(ws="w1", sid="new", created_at="2026-03-01"))
    rgh.add_entry(_entry(ws="w2", sid="other", created_at="2026-02-01"))
    out = rgh.entries_for_workspace("w1")
    assert [e.session_id for e in out] == ["new", "old"]  # mais recente primeiro
