import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from claude_workspaces.usage_telemetry import (
    aggregate_usage_by_workspace,
    format_tokens,
)


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
    proj_dir = fake_home / ".claude" / "projects" / "-home-italo-proj"
    proj_dir.mkdir()
    _write_assistant_msg(
        proj_dir / "s1.jsonl",
        cwd="/home/italo/proj",
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
    assert "/home/italo/proj" in out
    stats = out["/home/italo/proj"]
    assert stats.input_tokens == 1000
    assert stats.output_tokens == 500
    assert stats.cache_creation_tokens == 100
    assert stats.cache_read_tokens == 200
    assert stats.total_tokens == 1800
    assert stats.cost_usd > 0
    assert stats.sessions == 1


def test_aggregate_multiple_sessions_same_workspace(fake_home):
    proj_dir = fake_home / ".claude" / "projects" / "-home-italo-proj"
    proj_dir.mkdir()
    for i, fname in enumerate(["s1.jsonl", "s2.jsonl"]):
        _write_assistant_msg(
            proj_dir / fname,
            cwd="/home/italo/proj",
            model="claude-sonnet-4-6",
            tokens={"input_tokens": 100, "output_tokens": 50},
            ts=f"2026-05-1{5+i}T10:00:00Z",
        )
    out = aggregate_usage_by_workspace()
    assert out["/home/italo/proj"].sessions == 2
    assert out["/home/italo/proj"].input_tokens == 200


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
