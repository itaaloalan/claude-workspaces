"""Testes do skills_telemetry (aggregate_usage + find_zombies)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from claude_workspaces.skills_discovery import KIND_AGENT, KIND_SKILL, ClaudeItem
from claude_workspaces.skills_telemetry import (
    SkillUsage,
    aggregate_skill_usage,
    aggregate_usage,
    find_zombies,
)


def _write_session(dir_path: Path, name: str, lines: list[dict]) -> None:
    import json
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"{name}.jsonl").write_text(
        "\n".join(json.dumps(line) for line in lines), encoding="utf-8"
    )


def _assistant(ts: str, content: list[dict], cwd: str = "/proj") -> dict:
    return {
        "type": "assistant",
        "timestamp": ts,
        "cwd": cwd,
        "message": {"role": "assistant", "content": content},
    }


def _tool_use(tool_name: str, input_d: dict) -> dict:
    return {"type": "tool_use", "name": tool_name, "input": input_d}


def test_aggregate_usage_picks_up_skills_and_agents(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    proj = tmp_path / ".claude" / "projects" / "my-proj"
    _write_session(proj, "s1", [
        _assistant("2026-05-10T10:00:00Z", [
            _tool_use("Skill", {"skill": "commit-arquivo"}),
            _tool_use("Skill", {"skill": "commit-arquivo"}),
            _tool_use("Task", {"subagent_type": "Explore"}),
        ]),
        _assistant("2026-05-12T10:00:00Z", [
            _tool_use("Task", {"subagent_type": "Explore"}),
        ]),
    ])
    usage = aggregate_usage()
    assert usage[(KIND_SKILL, "commit-arquivo")].count == 2
    assert usage[(KIND_AGENT, "Explore")].count == 2


def test_aggregate_skill_usage_compat(tmp_path, monkeypatch):
    """Garante que a função antiga continua funcionando, ignorando agentes."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    proj = tmp_path / ".claude" / "projects" / "p"
    _write_session(proj, "s", [
        _assistant("2026-05-10T10:00:00Z", [
            _tool_use("Skill", {"skill": "x"}),
            _tool_use("Task", {"subagent_type": "agent-y"}),
        ]),
    ])
    skill_only = aggregate_skill_usage()
    assert "x" in skill_only
    assert "agent-y" not in skill_only


def test_aggregate_handles_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "nonexistent")
    assert aggregate_usage() == {}


def test_aggregate_ignores_malformed_lines(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    proj = tmp_path / ".claude" / "projects" / "p"
    proj.mkdir(parents=True)
    (proj / "junk.jsonl").write_text(
        '{"not": "valid"\nnot json at all\n{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"ok"}}]},"timestamp":"2026-05-10T10:00Z","cwd":"/x"}\n'
    )
    usage = aggregate_usage()
    assert (KIND_SKILL, "ok") in usage


def test_find_zombies_includes_unused(tmp_path):
    item = ClaudeItem(
        name="never", description="x", source="user",
        kind=KIND_SKILL, path=tmp_path / "never.md",
    )
    zombies = find_zombies([item], usage={}, threshold_days=30)
    assert zombies == [item]


def test_find_zombies_excludes_recent(tmp_path):
    item = ClaudeItem(
        name="used", description="x", source="user",
        kind=KIND_SKILL, path=tmp_path / "used.md",
    )
    usage = {
        (KIND_SKILL, "used"): SkillUsage(
            name="used",
            count=5,
            last_used=datetime.now(UTC) - timedelta(days=3),
        ),
    }
    assert find_zombies([item], usage, threshold_days=30) == []


def test_find_zombies_includes_stale(tmp_path):
    item = ClaudeItem(
        name="stale", description="x", source="user",
        kind=KIND_SKILL, path=tmp_path / "stale.md",
    )
    usage = {
        (KIND_SKILL, "stale"): SkillUsage(
            name="stale",
            count=2,
            last_used=datetime.now(UTC) - timedelta(days=60),
        ),
    }
    assert find_zombies([item], usage, threshold_days=30) == [item]


def test_find_zombies_skips_commands(tmp_path):
    """Commands não podem ser detectados como zumbis (sem sinal confiável)."""
    item = ClaudeItem(
        name="cmd", description="x", source="user",
        kind="command", path=tmp_path / "cmd.md",
    )
    assert find_zombies([item], usage={}, threshold_days=30) == []


def test_last_used_label():
    """Sanity check do label de tempo decorrido (já existia, regress)."""
    u = SkillUsage(name="x", count=1, last_used=datetime.now(UTC))
    assert u.last_used_label() in {"agora", "0h atrás"}
    u.last_used = datetime.now(UTC) - timedelta(days=2)
    assert "d atrás" in u.last_used_label()


# ---------------------------------------------------- cache por arquivo


def test_aggregate_usage_with_base_param(tmp_path):
    proj = tmp_path / "projects" / "p1"
    _write_session(proj, "s1", [
        _assistant("2026-05-10T10:00:00Z", [
            _tool_use("Skill", {"skill": "flyway"}),
        ]),
    ])
    usage = aggregate_usage(base=tmp_path / "projects")
    assert usage[(KIND_SKILL, "flyway")].count == 1


def test_aggregate_usage_cache_detects_file_change(tmp_path):
    proj = tmp_path / "projects" / "p1"
    _write_session(proj, "s1", [
        _assistant("2026-05-10T10:00:00Z", [
            _tool_use("Skill", {"skill": "flyway"}),
        ]),
    ])
    base = tmp_path / "projects"
    assert aggregate_usage(base=base)[(KIND_SKILL, "flyway")].count == 1
    # Reescreve com MAIS um uso (size muda → cache invalida).
    _write_session(proj, "s1", [
        _assistant("2026-05-10T10:00:00Z", [
            _tool_use("Skill", {"skill": "flyway"}),
        ]),
        _assistant("2026-05-11T10:00:00Z", [
            _tool_use("Skill", {"skill": "flyway"}),
        ]),
    ])
    assert aggregate_usage(base=base)[(KIND_SKILL, "flyway")].count == 2


def test_aggregate_usage_cache_skips_unchanged_file(tmp_path, monkeypatch):
    proj = tmp_path / "projects" / "p1"
    _write_session(proj, "s1", [
        _assistant("2026-05-10T10:00:00Z", [
            _tool_use("Skill", {"skill": "flyway"}),
        ]),
    ])
    base = tmp_path / "projects"
    assert aggregate_usage(base=base)[(KIND_SKILL, "flyway")].count == 1
    # Segunda agregação não deve REPARSEAR o arquivo intacto.
    import claude_workspaces.skills_telemetry as st
    calls = []
    orig = st._parse_file_invocations
    monkeypatch.setattr(
        st, "_parse_file_invocations",
        lambda p: (calls.append(str(p)), orig(p))[1],
    )
    assert aggregate_usage(base=base)[(KIND_SKILL, "flyway")].count == 1
    assert calls == [], "arquivo intacto reparseado (cache não funcionou)"
