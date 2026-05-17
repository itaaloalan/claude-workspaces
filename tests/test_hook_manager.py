"""Testes do hook_manager — install/uninstall do Stop hook em
~/.claude/settings.json. Tudo via monkeypatch das paths pra um tmp_path
isolado; nenhum arquivo real é tocado.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_workspaces import hook_manager


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch) -> Path:
    """Substitui ~ por tmp_path/home e cria packaging/notify-hook.py
    falso pra install_hook achar."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)

    # Cria um repo falso com packaging/notify-hook.py
    repo = tmp_path / "repo"
    pkg = repo / "packaging"
    pkg.mkdir(parents=True)
    (pkg / hook_manager.HOOK_FILENAME).write_text("#!/usr/bin/env python\n")

    monkeypatch.setattr(
        hook_manager,
        "_package_hook_script",
        lambda: pkg / hook_manager.HOOK_FILENAME,
    )
    return home


def _write_settings(home: Path, payload: dict) -> Path:
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(payload), encoding="utf-8")
    return settings


def test_paths_use_home(fake_home):
    assert str(fake_home) in str(hook_manager.claude_settings_file())
    assert str(fake_home) in str(hook_manager.installed_hook_script())


def test_is_hook_installed_false_when_settings_missing(fake_home):
    assert hook_manager.is_hook_installed() is False


def test_is_hook_installed_false_when_no_stop_hook(fake_home):
    _write_settings(fake_home, {"hooks": {"PreToolUse": []}})
    assert hook_manager.is_hook_installed() is False


def test_is_hook_installed_handles_corrupted_settings(fake_home):
    settings = fake_home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text("{ not valid json", encoding="utf-8")
    assert hook_manager.is_hook_installed() is False


def test_install_hook_writes_settings_and_copies_script(fake_home):
    dst = hook_manager.install_hook()
    assert dst.exists()
    # Script foi copiado pra app_data_dir
    assert dst == hook_manager.installed_hook_script()

    data = json.loads(
        hook_manager.claude_settings_file().read_text(encoding="utf-8")
    )
    stop = data["hooks"]["Stop"]
    assert len(stop) == 1
    cmd = stop[0]["hooks"][0]["command"]
    assert cmd.endswith(hook_manager.HOOK_FILENAME)

    assert hook_manager.is_hook_installed() is True


def test_install_hook_preserves_existing_hooks(fake_home):
    existing = {
        "hooks": {
            "Stop": [
                {"matcher": "x", "hooks": [{"type": "command", "command": "/other/script.sh"}]}
            ],
            "PreToolUse": [{"matcher": "", "hooks": []}],
        },
        "anyOtherKey": "preserved",
    }
    _write_settings(fake_home, existing)
    hook_manager.install_hook()

    data = json.loads(
        hook_manager.claude_settings_file().read_text(encoding="utf-8")
    )
    # User content preservado
    assert data["anyOtherKey"] == "preserved"
    assert data["hooks"]["PreToolUse"] == [{"matcher": "", "hooks": []}]
    # Original Stop hook preservado, novo adicionado
    stops = data["hooks"]["Stop"]
    assert len(stops) == 2
    cmds = [s["hooks"][0]["command"] for s in stops]
    assert "/other/script.sh" in cmds
    assert any(c.endswith(hook_manager.HOOK_FILENAME) for c in cmds)


def test_install_hook_idempotent(fake_home):
    hook_manager.install_hook()
    hook_manager.install_hook()  # 2ª vez não duplica
    data = json.loads(
        hook_manager.claude_settings_file().read_text(encoding="utf-8")
    )
    stops = data["hooks"]["Stop"]
    matching = [s for s in stops if s["hooks"][0]["command"].endswith(hook_manager.HOOK_FILENAME)]
    assert len(matching) == 1


def test_uninstall_hook_removes_only_our_entry(fake_home):
    # Setup: instala + adiciona hook de terceiro
    hook_manager.install_hook()
    settings = hook_manager.claude_settings_file()
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["hooks"]["Stop"].append(
        {"matcher": "y", "hooks": [{"type": "command", "command": "/third/party.sh"}]}
    )
    settings.write_text(json.dumps(data), encoding="utf-8")

    hook_manager.uninstall_hook()

    data = json.loads(settings.read_text(encoding="utf-8"))
    stops = data.get("hooks", {}).get("Stop", [])
    # Só sobrou o de terceiro
    assert len(stops) == 1
    assert stops[0]["hooks"][0]["command"] == "/third/party.sh"
    assert not hook_manager.installed_hook_script().exists()


def test_uninstall_hook_idempotent_no_settings(fake_home):
    # Sem settings.json nem script — não levanta
    hook_manager.uninstall_hook()


def test_uninstall_hook_cleans_up_empty_stop_and_hooks(fake_home):
    hook_manager.install_hook()
    hook_manager.uninstall_hook()

    data = json.loads(
        hook_manager.claude_settings_file().read_text(encoding="utf-8")
    )
    # `hooks` removido se vazio
    assert "hooks" not in data
