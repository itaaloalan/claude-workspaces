"""Testes do services/hooks_inspector."""

import json
from pathlib import Path

from claude_workspaces.services.hooks_inspector import (
    HOOK_EVENTS,
    SCOPE_LOCAL,
    SCOPE_PROJECT,
    SCOPE_USER,
    HookEntry,
    group_by_event,
    list_hooks,
)


def _write_settings(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_list_hooks_empty_when_no_files(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "empty")
    assert list_hooks(None) == []


def test_list_hooks_user_scope(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    _write_settings(tmp_path / ".claude" / "settings.json", {
        "hooks": {
            "Stop": [
                {"matcher": "", "hooks": [
                    {"type": "command", "command": "notify-send done"},
                ]},
            ],
        },
    })
    entries = list_hooks(None)
    assert len(entries) == 1
    e = entries[0]
    assert e.event == "Stop"
    assert e.scope == SCOPE_USER
    assert e.command == "notify-send done"


def test_list_hooks_project_scope(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    proj = tmp_path / "proj"
    _write_settings(proj / ".claude" / "settings.json", {
        "hooks": {
            "PostToolUse": [
                {"matcher": "Edit|Write", "hooks": [
                    {"type": "command", "command": "prettier --write", "timeout": 30},
                ]},
            ],
        },
    })
    entries = list_hooks([str(proj)])
    assert len(entries) == 1
    e = entries[0]
    assert e.event == "PostToolUse"
    assert e.scope == SCOPE_PROJECT
    assert e.matcher == "Edit|Write"
    assert e.timeout == 30


def test_list_hooks_local_scope(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    proj = tmp_path / "proj"
    _write_settings(proj / ".claude" / "settings.local.json", {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [
                    {"type": "command", "command": "echo running"},
                ]},
            ],
        },
    })
    entries = list_hooks([str(proj)])
    assert len(entries) == 1
    assert entries[0].scope == SCOPE_LOCAL


def test_list_hooks_combines_scopes(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    _write_settings(tmp_path / ".claude" / "settings.json", {
        "hooks": {"Stop": [{"matcher": "", "hooks": [
            {"type": "command", "command": "u1"},
        ]}]},
    })
    proj = tmp_path / "proj"
    _write_settings(proj / ".claude" / "settings.json", {
        "hooks": {"Stop": [{"matcher": "", "hooks": [
            {"type": "command", "command": "p1"},
        ]}]},
    })
    entries = list_hooks([str(proj)])
    scopes = [e.scope for e in entries]
    assert SCOPE_USER in scopes and SCOPE_PROJECT in scopes


def test_list_hooks_skips_malformed_json(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{ broken")
    assert list_hooks(None) == []


def test_list_hooks_skips_invalid_schema(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    _write_settings(tmp_path / ".claude" / "settings.json", {
        "hooks": "should be dict",
    })
    assert list_hooks(None) == []


def test_list_hooks_skips_empty_commands(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    _write_settings(tmp_path / ".claude" / "settings.json", {
        "hooks": {"Stop": [{"matcher": "", "hooks": [
            {"type": "command", "command": ""},
            {"type": "command", "command": "valid"},
        ]}]},
    })
    entries = list_hooks(None)
    assert len(entries) == 1
    assert entries[0].command == "valid"


def test_short_command_truncates():
    e = HookEntry(
        scope="user", event="Stop", matcher="", command="x" * 200,
        type_="command", timeout=None, source_file=Path("/x"),
    )
    assert len(e.short_command()) <= 80
    assert e.short_command().endswith("…")


def test_group_by_event_orders_known_first():
    e1 = HookEntry("user", "PostToolUse", "", "a", "command", None, Path("/x"))
    e2 = HookEntry("user", "Stop", "", "b", "command", None, Path("/x"))
    e3 = HookEntry("user", "CustomXYZ", "", "c", "command", None, Path("/x"))
    grouped = group_by_event([e1, e2, e3])
    keys = list(grouped.keys())
    # PostToolUse e Stop estão em HOOK_EVENTS, CustomXYZ não
    assert keys.index("PostToolUse") < keys.index("CustomXYZ")
    assert keys.index("Stop") < keys.index("CustomXYZ")


def test_hook_events_constant_includes_common_ones():
    for ev in ("Stop", "PreToolUse", "PostToolUse"):
        assert ev in HOOK_EVENTS
