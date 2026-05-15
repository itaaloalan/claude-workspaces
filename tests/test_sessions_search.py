import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from claude_workspaces.sessions_search import search_sessions


def _write_session(jsonl_path: Path, messages: list[dict]):
    with jsonl_path.open("w", encoding="utf-8") as fp:
        for m in messages:
            fp.write(json.dumps(m) + "\n")


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".claude" / "projects").mkdir(parents=True)
    return tmp_path


def test_empty_query(fake_home):
    assert search_sessions("") == []


def test_empty_dir(fake_home):
    assert search_sessions("anything") == []


def test_finds_match_in_user_message(fake_home):
    proj = fake_home / ".claude" / "projects" / "-proj"
    proj.mkdir()
    _write_session(proj / "s1.jsonl", [
        {
            "type": "user",
            "message": {"content": "refatorar BoletimMensal"},
        }
    ])
    hits = search_sessions("Boletim")
    assert len(hits) == 1
    assert hits[0].match_count == 1
    assert "BoletimMensal" in hits[0].snippet


def test_finds_match_in_assistant_text_content(fake_home):
    proj = fake_home / ".claude" / "projects" / "-proj"
    proj.mkdir()
    _write_session(proj / "s.jsonl", [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "vou editar src/Foo.java"},
                ],
            },
        }
    ])
    hits = search_sessions("editar")
    assert len(hits) == 1


def test_match_count(fake_home):
    proj = fake_home / ".claude" / "projects" / "-proj"
    proj.mkdir()
    _write_session(proj / "s.jsonl", [
        {"type": "user", "message": {"content": "foo bar foo baz foo"}}
    ])
    hits = search_sessions("foo")
    assert hits[0].match_count == 3


def test_case_insensitive(fake_home):
    proj = fake_home / ".claude" / "projects" / "-proj"
    proj.mkdir()
    _write_session(proj / "s.jsonl", [
        {"type": "user", "message": {"content": "BoLeTiM"}}
    ])
    assert len(search_sessions("boletim")) == 1


def test_first_prompt_extracted(fake_home):
    proj = fake_home / ".claude" / "projects" / "-proj"
    proj.mkdir()
    _write_session(proj / "s.jsonl", [
        {"type": "user", "message": {"content": "primeiro prompt"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "resposta"}]}},
        {"type": "user", "message": {"content": "segundo prompt"}},
    ])
    hits = search_sessions("prompt")
    assert hits[0].first_prompt == "primeiro prompt"


def test_since_filter_by_mtime(fake_home):
    proj = fake_home / ".claude" / "projects" / "-proj"
    proj.mkdir()
    # Cria arquivo antigo
    old = proj / "old.jsonl"
    _write_session(old, [{"type": "user", "message": {"content": "termo unico"}}])
    import os
    # Mtime há 10 anos atrás
    old_ts = (datetime.now(UTC) - timedelta(days=3650)).timestamp()
    os.utime(old, (old_ts, old_ts))

    new = proj / "new.jsonl"
    _write_session(new, [{"type": "user", "message": {"content": "termo unico"}}])

    # since = ontem → só pega o novo
    since = datetime.now(UTC) - timedelta(days=1)
    hits = search_sessions("termo unico", since=since)
    assert len(hits) == 1
    assert hits[0].file_path == new


def test_results_ordered_by_recency(fake_home):
    proj = fake_home / ".claude" / "projects" / "-proj"
    proj.mkdir()
    import os
    for i, name in enumerate(["a.jsonl", "b.jsonl", "c.jsonl"]):
        f = proj / name
        _write_session(f, [{"type": "user", "message": {"content": "match"}}])
        ts = (datetime.now(UTC) - timedelta(days=10 - i)).timestamp()
        os.utime(f, (ts, ts))
    hits = search_sessions("match")
    assert len(hits) == 3
    # Mais recente primeiro: c, b, a
    assert hits[0].file_path.name == "c.jsonl"
    assert hits[-1].file_path.name == "a.jsonl"


def test_no_match(fake_home):
    proj = fake_home / ".claude" / "projects" / "-proj"
    proj.mkdir()
    _write_session(proj / "s.jsonl", [
        {"type": "user", "message": {"content": "outro texto"}}
    ])
    assert search_sessions("nada disso") == []


def test_invalid_jsonl_lines_skipped(fake_home):
    proj = fake_home / ".claude" / "projects" / "-proj"
    proj.mkdir()
    f = proj / "s.jsonl"
    f.write_text(
        '{"invalid json without closing\n'
        + '{"type": "user", "message": {"content": "valid"}}\n'
    )
    hits = search_sessions("valid")
    assert len(hits) == 1
