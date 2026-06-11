import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import claude_workspaces.usage_telemetry as ut
from claude_workspaces.usage_telemetry import (
    aggregate_usage_by_workspace,
    format_tokens,
    usage_for_session,
)


@pytest.fixture(autouse=True)
def clear_session_cache():
    ut._session_cache.clear()
    yield
    ut._session_cache.clear()


def _write_assistant_msg(jsonl_path: Path, cwd: str, model: str, tokens: dict, ts: str):
    msg = {
        "type": "assistant",
        "cwd": cwd,
        "timestamp": ts,
        "message": {
            "model": model,
            "usage": tokens,
        },
    }
    with jsonl_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(msg) + "\n")


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    base = tmp_path / ".claude" / "projects"
    base.mkdir(parents=True)
    return tmp_path


def test_aggregate_empty(fake_home):
    assert aggregate_usage_by_workspace() == {}


def test_aggregate_single_session(fake_home):
    proj_dir = fake_home / ".claude" / "projects" / "-home-user-proj"
    proj_dir.mkdir()
    _write_assistant_msg(
        proj_dir / "s1.jsonl",
        cwd="/home/user/proj",
        model="claude-opus-4-7",
        tokens={
            "input_tokens": 1000,
            "output_tokens": 500,
            "cache_creation_input_tokens": 100,
            "cache_read_input_tokens": 200,
        },
        ts="2026-05-15T10:00:00Z",
    )
    out = aggregate_usage_by_workspace()
    assert "/home/user/proj" in out
    stats = out["/home/user/proj"]
    assert stats.input_tokens == 1000
    assert stats.output_tokens == 500
    assert stats.cache_creation_tokens == 100
    assert stats.cache_read_tokens == 200
    assert stats.total_tokens == 1800
    assert stats.cost_usd > 0
    assert stats.sessions == 1


def test_aggregate_multiple_sessions_same_workspace(fake_home):
    proj_dir = fake_home / ".claude" / "projects" / "-home-user-proj"
    proj_dir.mkdir()
    for i, fname in enumerate(["s1.jsonl", "s2.jsonl"]):
        _write_assistant_msg(
            proj_dir / fname,
            cwd="/home/user/proj",
            model="claude-sonnet-4-6",
            tokens={"input_tokens": 100, "output_tokens": 50},
            ts=f"2026-05-1{5+i}T10:00:00Z",
        )
    out = aggregate_usage_by_workspace()
    assert out["/home/user/proj"].sessions == 2
    assert out["/home/user/proj"].input_tokens == 200


def test_aggregate_uses_cwd_not_dir_name(fake_home):
    """O 'cwd' real vem da mensagem, não do dir name (que é lossy)."""
    # Cria dir codificado de jeito esquisito (com hífen real)
    proj_dir = fake_home / ".claude" / "projects" / "-home-x-map-api"
    proj_dir.mkdir()
    real_cwd = "/home/x/map-api"  # tem hífen real, vs separador
    _write_assistant_msg(
        proj_dir / "s.jsonl",
        cwd=real_cwd,
        model="claude-haiku-4-5",
        tokens={"input_tokens": 10, "output_tokens": 5},
        ts="2026-05-15T10:00:00Z",
    )
    out = aggregate_usage_by_workspace()
    assert real_cwd in out  # preserva o hífen original


def test_since_filter(fake_home):
    proj_dir = fake_home / ".claude" / "projects" / "-x"
    proj_dir.mkdir()
    _write_assistant_msg(
        proj_dir / "old.jsonl",
        cwd="/x",
        model="claude-opus-4-7",
        tokens={"input_tokens": 1000, "output_tokens": 500},
        ts="2020-01-01T00:00:00Z",
    )
    _write_assistant_msg(
        proj_dir / "new.jsonl",
        cwd="/x",
        model="claude-opus-4-7",
        tokens={"input_tokens": 50, "output_tokens": 30},
        ts="2026-05-15T00:00:00Z",
    )
    since = datetime(2026, 1, 1, tzinfo=UTC)
    out = aggregate_usage_by_workspace(since=since)
    assert out["/x"].input_tokens == 50  # só a nova
    assert out["/x"].output_tokens == 30


def test_unknown_model_zero_cost(fake_home):
    proj_dir = fake_home / ".claude" / "projects" / "-y"
    proj_dir.mkdir()
    _write_assistant_msg(
        proj_dir / "s.jsonl",
        cwd="/y",
        model="modelo-inexistente-v999",
        tokens={"input_tokens": 1000, "output_tokens": 500},
        ts="2026-05-15T10:00:00Z",
    )
    out = aggregate_usage_by_workspace()
    assert out["/y"].input_tokens == 1000
    assert out["/y"].cost_usd == 0  # sem preço cadastrado


def test_ignores_non_assistant_messages(fake_home):
    proj_dir = fake_home / ".claude" / "projects" / "-z"
    proj_dir.mkdir()
    user_msg = {
        "type": "user",
        "cwd": "/z",
        "timestamp": "2026-05-15T10:00:00Z",
        "message": {"content": "hello"},
    }
    (proj_dir / "s.jsonl").write_text(json.dumps(user_msg) + "\n")
    out = aggregate_usage_by_workspace()
    assert out == {}


def test_format_tokens():
    assert format_tokens(500) == "500"
    assert format_tokens(1500) == "1.5K"
    assert format_tokens(2_500_000) == "2.5M"


# ---- usage_for_session: cache incremental ---------------------------------


def _session_file(tmp_path: Path) -> Path:
    return tmp_path / "sessao.jsonl"


def _msg(model: str = "claude-sonnet-4-6", inp: int = 100, out: int = 50,
         ts: str = "2026-05-15T10:00:00Z") -> str:
    return json.dumps({
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "model": model,
            "usage": {"input_tokens": inp, "output_tokens": out},
        },
    })


def _fresh_parse(path: Path):
    """Parse com cache limpo — referência de verdade pro incremental."""
    ut._session_cache.clear()
    stats = usage_for_session(path)
    return stats


def test_session_warm_equals_cold_after_append(tmp_path):
    f = _session_file(tmp_path)
    f.write_text(_msg(inp=100) + "\n")
    first = usage_for_session(f)
    assert first.input_tokens == 100
    # Append → próxima chamada (warm, incremental) tem que bater com um
    # parse completo de cache limpo.
    with f.open("a") as fp:
        fp.write(_msg(model="claude-opus-4-7", inp=7, out=3,
                      ts="2026-05-15T11:00:00Z") + "\n")
    warm = usage_for_session(f)
    cold = _fresh_parse(f)
    assert warm == cold
    assert warm.input_tokens == 107
    assert warm.last_model == "claude-opus-4-7"
    assert warm.by_model == cold.by_model


def test_session_cache_hit_returns_copy(tmp_path):
    f = _session_file(tmp_path)
    f.write_text(_msg() + "\n")
    a = usage_for_session(f)
    a.by_model["mutado"] = 999
    a.input_tokens = -1
    b = usage_for_session(f)
    assert "mutado" not in b.by_model
    assert b.input_tokens == 100


def test_session_truncation_forces_full_reparse(tmp_path):
    f = _session_file(tmp_path)
    f.write_text(_msg(inp=100) + "\n" + _msg(inp=200) + "\n")
    assert usage_for_session(f).input_tokens == 300
    # Trunca pra um arquivo menor com conteúdo diferente.
    f.write_text(_msg(inp=5) + "\n")
    assert usage_for_session(f).input_tokens == 5


def test_session_rewrite_larger_detected_by_tail(tmp_path):
    f = _session_file(tmp_path)
    f.write_text(_msg(inp=100) + "\n")
    assert usage_for_session(f).input_tokens == 100
    # Rewrite completo (mesmo inode, tamanho MAIOR): sem o tail-check o
    # incremental partiria do offset antigo e somaria errado.
    f.write_text(_msg(inp=1) + "\n" + _msg(inp=2) + "\n" + _msg(inp=4) + "\n")
    assert usage_for_session(f).input_tokens == 7


def test_session_partial_line_ignored_then_consumed(tmp_path):
    f = _session_file(tmp_path)
    line = _msg(inp=100)
    f.write_text(line + "\n")
    assert usage_for_session(f).input_tokens == 100
    # Append parcial (sem \n) — não conta ainda.
    extra = _msg(inp=50, ts="2026-05-15T11:00:00Z")
    with f.open("a") as fp:
        fp.write(extra[:10])
    assert usage_for_session(f).input_tokens == 100
    # Completa a linha — agora conta, e bate com parse frio.
    with f.open("a") as fp:
        fp.write(extra[10:] + "\n")
    warm = usage_for_session(f)
    assert warm.input_tokens == 150
    assert warm == _fresh_parse(f)


def test_session_cache_eviction_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(ut, "_SESSION_CACHE_MAX", 3)
    for i in range(5):
        f = tmp_path / f"s{i}.jsonl"
        f.write_text(_msg(inp=i + 1) + "\n")
        usage_for_session(f)
    assert len(ut._session_cache) <= 3
