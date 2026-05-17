import json

import pytest

from claude_workspaces import session_persistence, storage
from claude_workspaces.session_persistence import (
    SavedSession,
    clear_saved_sessions,
    load_saved_sessions,
    save_sessions,
    session_state_file,
)


@pytest.fixture
def patched_config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(session_persistence, "config_dir", lambda: tmp_path)
    return tmp_path


def test_load_empty_when_no_file(patched_config_dir):
    assert load_saved_sessions() == []


def test_save_and_load_roundtrip(patched_config_dir):
    sessions = [
        SavedSession(workspace_id="ws1", session_id="abc123", cwd="/tmp/a"),
        SavedSession(workspace_id="ws2", session_id="def456", cwd="/tmp/b"),
    ]
    save_sessions(sessions)

    loaded = load_saved_sessions()
    assert len(loaded) == 2
    assert loaded[0].workspace_id == "ws1"
    assert loaded[0].session_id == "abc123"
    assert loaded[0].cwd == "/tmp/a"
    assert loaded[1].session_id == "def456"


def test_save_drops_invalid_entries(patched_config_dir):
    """Entradas com campos vazios são descartadas — nada de --resume sem id."""
    sessions = [
        SavedSession(workspace_id="ws1", session_id="abc", cwd="/tmp/a"),
        SavedSession(workspace_id="", session_id="def", cwd="/tmp/b"),
        SavedSession(workspace_id="ws2", session_id="", cwd="/tmp/c"),
        SavedSession(workspace_id="ws3", session_id="ghi", cwd=""),
    ]
    save_sessions(sessions)
    loaded = load_saved_sessions()
    assert len(loaded) == 1
    assert loaded[0].session_id == "abc"


def test_load_skips_malformed_entries(patched_config_dir):
    """Arquivo corrompido / entradas não-dict não derrubam o load."""
    path = session_state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "sessions": [
            {"workspace_id": "ws1", "session_id": "abc", "cwd": "/tmp/a"},
            "isso não é dict",
            {"workspace_id": "ws2"},  # faltando campos
            None,
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = load_saved_sessions()
    assert len(loaded) == 1
    assert loaded[0].session_id == "abc"


def test_load_returns_empty_on_corrupt_json(patched_config_dir):
    path = session_state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("não é json válido {{{", encoding="utf-8")
    assert load_saved_sessions() == []


def test_clear_saved_sessions_removes_file(patched_config_dir):
    save_sessions([SavedSession("ws1", "abc", "/tmp/a")])
    assert session_state_file().exists()
    clear_saved_sessions()
    assert not session_state_file().exists()


def test_clear_is_noop_when_no_file(patched_config_dir):
    clear_saved_sessions()  # não deve levantar
    assert not session_state_file().exists()


def test_session_file_path_uses_encoded_project_dir(patched_config_dir):
    s = SavedSession(workspace_id="ws", session_id="abc", cwd="/home/x/proj")
    # claude_sessions encoda barras como '-'
    assert s.session_file().name == "abc.jsonl"
    assert "home-x-proj" in str(s.session_file())


def test_save_creates_directory(tmp_path, monkeypatch):
    nested = tmp_path / "deep" / "nested"
    monkeypatch.setattr(session_persistence, "config_dir", lambda: nested)
    save_sessions([SavedSession("ws1", "abc", "/tmp/a")])
    assert (nested / "session_state.json").exists()
