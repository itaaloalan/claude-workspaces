import json

from claude_workspaces.notifications.discord_summary import (
    EMBED_TITLE_LIMIT,
    compute_metrics,
    encode_project_dir,
    format_metrics,
    make_title,
    resolve_transcript,
    split_body,
)

# ---------------- encode_project_dir ----------------

def test_encode_project_dir():
    assert encode_project_dir("/home/italo/Projetos/x") == "-home-italo-Projetos-x"
    # trailing slash não muda o resultado
    assert encode_project_dir("/home/italo/Projetos/x/") == "-home-italo-Projetos-x"


# ---------------- split_body ----------------

def test_split_body_short_is_single():
    assert split_body("oi", limit=100) == ["oi"]


def test_split_body_respects_limit_on_newlines():
    text = "\n".join(["linha"] * 50)  # ~300 chars
    parts = split_body(text, limit=60)
    assert len(parts) > 1
    assert all(len(p) <= 60 for p in parts)
    # nada se perde
    assert "\n".join(parts).replace("\n", "") == text.replace("\n", "")


def test_split_body_oversized_single_line_is_hard_cut():
    text = "x" * 250
    parts = split_body(text, limit=100)
    assert all(len(p) <= 100 for p in parts)
    assert "".join(parts) == text


# ---------------- make_title ----------------

def test_make_title_single_part_no_marker():
    assert make_title("Resumo", 1, 1) == "Resumo"


def test_make_title_preserves_part_marker_when_truncating():
    base = "A" * 300
    t = make_title(base, 2, 3)
    assert len(t) <= EMBED_TITLE_LIMIT
    assert t.endswith("(parte 2/3)")


def test_make_title_short_base_keeps_full():
    assert make_title("Deploy", 1, 2) == "Deploy (parte 1/2)"


# ---------------- compute_metrics / format_metrics ----------------

def _write_transcript(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")


def test_compute_metrics_aggregates(tmp_path):
    f = tmp_path / "s.jsonl"
    _write_transcript(f, [
        {"timestamp": "2026-05-25T20:00:00Z",
         "message": {"model": "claude-opus-4-7",
                     "usage": {"input_tokens": 10, "output_tokens": 5,
                               "cache_read_input_tokens": 100,
                               "cache_creation_input_tokens": 20}}},
        {"timestamp": "2026-05-25T20:09:00Z",
         "message": {"model": "claude-opus-4-7",
                     "usage": {"input_tokens": 2, "output_tokens": 3}}},
        {"timestamp": "2026-05-25T20:10:00Z", "message": {"role": "user"}},  # sem usage
        "linha lixo não-json",
    ])
    m = compute_metrics(f)
    assert m.turns == 2
    assert m.input_tokens == 12
    assert m.output_tokens == 8
    assert m.total_tokens == 20
    assert m.cache_read == 100
    assert m.cache_creation == 20
    assert m.models == ("claude-opus-4-7",)
    assert m.duration_min == 10


def test_compute_metrics_none_for_missing():
    assert compute_metrics(None) is None


def test_format_metrics_empty_when_no_turns(tmp_path):
    f = tmp_path / "s.jsonl"
    _write_transcript(f, [{"message": {"role": "user"}}])
    assert format_metrics(compute_metrics(f)) == ""


def test_format_metrics_renders(tmp_path):
    f = tmp_path / "s.jsonl"
    _write_transcript(f, [
        {"timestamp": "2026-05-25T20:00:00Z",
         "message": {"model": "claude-opus-4-7",
                     "usage": {"input_tokens": 1000, "output_tokens": 2000}}},
        {"timestamp": "2026-05-25T20:05:00Z",
         "message": {"model": "claude-opus-4-7",
                     "usage": {"input_tokens": 0, "output_tokens": 0}}},
    ])
    out = format_metrics(compute_metrics(f))
    assert "📊 Sessão" in out
    assert "3,000 tokens" in out
    assert "⏱ 5 min" in out
    assert "claude-opus-4-7" in out


# ---------------- resolve_transcript ----------------

def test_resolve_transcript_by_session_id(tmp_path):
    cwd = "/home/u/proj"
    d = tmp_path / ".claude" / "projects" / encode_project_dir(cwd)
    d.mkdir(parents=True)
    (d / "aaa.jsonl").write_text("{}", encoding="utf-8")
    (d / "bbb.jsonl").write_text("{}", encoding="utf-8")
    got = resolve_transcript(cwd, session_id="aaa", home=tmp_path, env={})
    assert got == d / "aaa.jsonl"


def test_resolve_transcript_env_override(tmp_path):
    cwd = "/home/u/proj"
    d = tmp_path / ".claude" / "projects" / encode_project_dir(cwd)
    d.mkdir(parents=True)
    (d / "ccc.jsonl").write_text("{}", encoding="utf-8")
    got = resolve_transcript(cwd, home=tmp_path, env={"CLAUDE_SESSION_ID": "ccc"})
    assert got == d / "ccc.jsonl"


def test_resolve_transcript_fallback_most_recent(tmp_path):
    import os
    cwd = "/home/u/proj"
    d = tmp_path / ".claude" / "projects" / encode_project_dir(cwd)
    d.mkdir(parents=True)
    old = d / "old.jsonl"
    old.write_text("{}", encoding="utf-8")
    new = d / "new.jsonl"
    new.write_text("{}", encoding="utf-8")
    # garante mtimes distintos
    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))
    got = resolve_transcript(cwd, home=tmp_path, env={})
    assert got == new


def test_resolve_transcript_missing_dir_is_none(tmp_path):
    assert resolve_transcript("/no/such/proj", home=tmp_path, env={}) is None


def test_resolve_transcript_bad_id_falls_back(tmp_path):
    cwd = "/home/u/proj"
    d = tmp_path / ".claude" / "projects" / encode_project_dir(cwd)
    d.mkdir(parents=True)
    (d / "real.jsonl").write_text("{}", encoding="utf-8")
    got = resolve_transcript(cwd, session_id="inexistente", home=tmp_path, env={})
    assert got == d / "real.jsonl"
