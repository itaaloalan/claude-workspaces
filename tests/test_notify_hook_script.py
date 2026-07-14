"""Testes do packaging/notify-hook.py — script standalone (não faz parte
do pacote, roda como subprocess do Claude Code) carregado por caminho.

Cobre a regressão: desmarcar "notificação nativa" na UI do app não bastava
pra silenciar tudo — esse hook roda independente do processo do app e
ignorava o flag `notify_native_enabled`, notificando a cada fim de turno.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "packaging" / "notify-hook.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("notify_hook_script", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def hook_mod():
    return _load_module()


@pytest.fixture
def fake_config_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".config" / "claude-workspaces").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


def _write_settings(home: Path, **overrides) -> None:
    path = home / ".config" / "claude-workspaces" / "settings.json"
    path.write_text(json.dumps(overrides), encoding="utf-8")


def test_native_disabled_skips_notification(hook_mod, fake_config_home, monkeypatch, capsys):
    _write_settings(fake_config_home, notify_native_enabled=False)
    calls = []
    monkeypatch.setattr(hook_mod, "_send_dbus", lambda *a, **k: calls.append(a) or True)
    monkeypatch.setattr(hook_mod, "_send_notify_send", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(
        "sys.stdin", __import__("io").StringIO(json.dumps({"cwd": "/tmp"}))
    )
    rc = hook_mod.main()
    assert rc == 0
    assert calls == []


def test_native_enabled_sends_notification(hook_mod, fake_config_home, monkeypatch):
    _write_settings(fake_config_home, notify_native_enabled=True)
    calls = []
    monkeypatch.setattr(hook_mod, "_send_dbus", lambda *a, **k: calls.append(a) or True)
    monkeypatch.setattr(hook_mod, "_send_notify_send", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(
        "sys.stdin", __import__("io").StringIO(json.dumps({"cwd": "/tmp"}))
    )
    rc = hook_mod.main()
    assert rc == 0
    assert len(calls) == 1


def test_missing_flag_defaults_to_enabled(hook_mod, fake_config_home, monkeypatch):
    """Sem o campo (settings.json antigo/config vazia), o comportamento
    default continua notificando — só `False` explícito silencia."""
    _write_settings(fake_config_home)
    calls = []
    monkeypatch.setattr(hook_mod, "_send_dbus", lambda *a, **k: calls.append(a) or True)
    monkeypatch.setattr(hook_mod, "_send_notify_send", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(
        "sys.stdin", __import__("io").StringIO(json.dumps({"cwd": "/tmp"}))
    )
    rc = hook_mod.main()
    assert rc == 0
    assert len(calls) == 1
