"""Testes de opencode_sessions.py — leitura do DB sqlite do OpenCode.

Cria um DB sqlite temporário com o schema mínimo (session/message/part) e
monkeypatcha `_opencode_db` para apontar pra ele.
"""

import json
import sqlite3

import pytest

from claude_workspaces import opencode_sessions as oc
from claude_workspaces.opencode_sessions import OpencodeSession


def _build_db(path):
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE session (
            id TEXT, slug TEXT, directory TEXT, title TEXT,
            time_created INTEGER, time_updated INTEGER,
            agent TEXT, model TEXT, tokens_input INTEGER, tokens_output INTEGER
        );
        CREATE TABLE message (
            id TEXT, session_id TEXT, data TEXT, time_created INTEGER
        );
        CREATE TABLE part (
            message_id TEXT, data TEXT, time_created INTEGER
        );
        """
    )
    conn.commit()
    conn.close()


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "opencode.db"
    _build_db(path)
    monkeypatch.setattr(oc, "_opencode_db", lambda: path)
    return path


def _add_session(path, *, sid, directory, title="t", time_updated=1000,
                 model='{"id": "gpt-4"}', agent="build", slug="s"):
    conn = sqlite3.connect(str(path))
    conn.execute(
        "INSERT INTO session VALUES (?,?,?,?,?,?,?,?,?,?)",
        (sid, slug, directory, title, time_updated, time_updated,
         agent, model, 0, 0),
    )
    conn.commit()
    conn.close()


def _add_message(path, *, mid, sid, role, text, t=1):
    conn = sqlite3.connect(str(path))
    conn.execute(
        "INSERT INTO message VALUES (?,?,?,?)",
        (mid, sid, json.dumps({"role": role}), t),
    )
    conn.execute(
        "INSERT INTO part VALUES (?,?,?)",
        (mid, json.dumps({"type": "text", "text": text}), t),
    )
    conn.commit()
    conn.close()


# ---------- OpencodeSession.label (puro) ----------

def _sess(**kw):
    kw.setdefault("id", "s1")
    kw.setdefault("mtime", 0.0)
    kw.setdefault("preview", "")
    kw.setdefault("path", "/db")
    kw.setdefault("origin_cwd", "/home/me/proj")
    kw.setdefault("directory", "/home/me/proj")
    kw.setdefault("title", "")
    kw.setdefault("slug", "s")
    return OpencodeSession(**kw)


def test_label_uses_preview():
    s = _sess(preview="corrigir bug")
    assert "corrigir bug" in s.label()


def test_label_falls_back_to_title():
    s = _sess(preview="", title="meu título")
    assert "meu título" in s.label()


def test_label_no_preview_or_title():
    assert "(sem título)" in _sess(preview="", title="").label()


def test_label_truncates_preview():
    s = _sess(preview="x" * 200)
    out = s.label(max_preview=20)
    assert "…" in out


def test_label_include_origin_prefix():
    s = _sess(origin_cwd="/home/me/projeto")
    assert s.label(include_origin=True).startswith("[projeto]")


# ---------- _read_first_user_message ----------

def test_read_first_user_message_missing_db(tmp_path, monkeypatch):
    monkeypatch.setattr(oc, "_opencode_db", lambda: tmp_path / "nope.db")
    assert oc._read_first_user_message("s1") == ""


def test_read_first_user_message_returns_text(db):
    _add_session(db, sid="s1", directory="/p")
    _add_message(db, mid="m1", sid="s1", role="user", text="primeira pergunta")
    assert oc._read_first_user_message("s1") == "primeira pergunta"


def test_read_first_user_message_skips_assistant(db):
    _add_session(db, sid="s1", directory="/p")
    _add_message(db, mid="m1", sid="s1", role="assistant", text="resposta", t=1)
    _add_message(db, mid="m2", sid="s1", role="user", text="pergunta", t=2)
    assert oc._read_first_user_message("s1") == "pergunta"


# ---------- list_sessions ----------

def test_list_sessions_missing_db(tmp_path, monkeypatch):
    monkeypatch.setattr(oc, "_opencode_db", lambda: tmp_path / "nope.db")
    assert oc.list_sessions("/p") == []


def test_list_sessions_filters_by_directory(db):
    _add_session(db, sid="a", directory="/proj-a")
    _add_session(db, sid="b", directory="/proj-b")
    out = oc.list_sessions("/proj-a")
    assert [s.id for s in out] == ["a"]


def test_list_sessions_parses_model_json(db):
    _add_session(db, sid="a", directory="/p", model='{"id": "claude-opus"}')
    assert oc.list_sessions("/p")[0].model == "claude-opus"


def test_list_sessions_model_non_json_fallback(db):
    _add_session(db, sid="a", directory="/p", model="raw-model")
    assert oc.list_sessions("/p")[0].model == "raw-model"


def test_list_sessions_orders_by_time_updated_desc(db):
    _add_session(db, sid="old", directory="/p", time_updated=1000)
    _add_session(db, sid="new", directory="/p", time_updated=5000)
    assert [s.id for s in oc.list_sessions("/p")] == ["new", "old"]


def test_list_sessions_attaches_preview(db):
    _add_session(db, sid="a", directory="/p")
    _add_message(db, mid="m1", sid="a", role="user", text="olá mundo")
    assert oc.list_sessions("/p")[0].preview == "olá mundo"


def test_list_sessions_mtime_is_ms_divided(db):
    _add_session(db, sid="a", directory="/p", time_updated=5000)
    assert oc.list_sessions("/p")[0].mtime == 5.0


# ---------- list_sessions_for_paths ----------

def test_list_sessions_for_paths_dedups_and_sorts(tmp_path, monkeypatch):
    path = tmp_path / "opencode.db"
    _build_db(path)
    monkeypatch.setattr(oc, "_opencode_db", lambda: path)
    monkeypatch.setattr(
        "claude_workspaces.session_marks.starred_ids", lambda: set()
    )
    d = str(tmp_path)
    _add_session(path, sid="a", directory=d, time_updated=1000)
    _add_session(path, sid="b", directory=d, time_updated=9000)
    # mesmo path repetido não duplica
    out = oc.list_sessions_for_paths([d, d])
    assert [s.id for s in out] == ["b", "a"]
