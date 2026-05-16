"""Testes do PluginHost: ctx.workspaces/sessions com permissões + providers."""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

# Garante Qt em modo headless antes de importar plugin_host (que usa QObject)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# QApplication tem que existir antes do QObject — força criação local.
if "PySide6.QtWidgets" not in sys.modules:  # pragma: no cover
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])  # noqa: B018
else:
    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is None:
        QApplication([])

from claude_workspaces.plugin_api import Session, Workspace
from claude_workspaces.services.plugin_host import (  # noqa: E402
    PluginHost,
    _PluginSessions,
    _PluginWorkspaces,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# -------------------- ctx.workspaces ----------------------------------------


def _ws(id_: str, name: str = "w") -> Workspace:
    return Workspace(id=id_, name=name, folders=("/x",))


class _FakePlugin:
    """Mínimo necessário pros _Plugin{Workspaces,Sessions}."""

    def __init__(self, perms) -> None:
        from types import SimpleNamespace

        self.id = "test"
        self.manifest = SimpleNamespace(permissions=perms)


def _perms(workspaces="all"):
    from claude_workspaces.plugins.manifest import (
        FilesystemPermissions,
        NetworkPermissions,
        Permissions,
    )
    return Permissions(
        filesystem=FilesystemPermissions(),
        network=NetworkPermissions(),
        notifications=False,
        workspaces=workspaces,
    )


def test_workspaces_all_allows_everything():
    workspaces = [_ws("a"), _ws("b")]
    api = _PluginWorkspaces(
        list_provider=lambda: workspaces,
        current_provider=lambda: workspaces[0],
        inst=_FakePlugin(_perms("all")),
    )
    assert {w.id for w in _run(api.list())} == {"a", "b"}
    assert _run(api.current()).id == "a"
    assert _run(api.get("b")).id == "b"


def test_workspaces_filtered_by_permission():
    workspaces = [_ws("a"), _ws("b"), _ws("c")]
    api = _PluginWorkspaces(
        list_provider=lambda: workspaces,
        current_provider=lambda: workspaces[2],  # 'c' não está autorizado
        inst=_FakePlugin(_perms(workspaces=("a", "b"))),
    )
    assert {w.id for w in _run(api.list())} == {"a", "b"}
    assert _run(api.current()) is None  # 'c' filtrado
    assert _run(api.get("a")).id == "a"
    with pytest.raises(PermissionError):
        _run(api.get("c"))


def test_workspace_get_missing_raises():
    api = _PluginWorkspaces(
        list_provider=lambda: [_ws("a")],
        current_provider=lambda: None,
        inst=_FakePlugin(_perms("all")),
    )
    with pytest.raises(KeyError):
        _run(api.get("zzz"))


# -------------------- ctx.sessions ------------------------------------------


def _sess(id_: str, ws_id: str, status: str = "running") -> Session:
    return Session(
        id=id_, workspace_id=ws_id, workspace_name=ws_id,
        status=status, last_message=None,
    )


def test_sessions_filtered_by_workspace_permission():
    sessions = [_sess("s1", "a"), _sess("s2", "b"), _sess("s3", "c")]
    focused: list[str] = []
    api = _PluginSessions(
        list_provider=lambda _status: sessions,
        focus_fn=focused.append,
        inst=_FakePlugin(_perms(workspaces=("a", "b"))),
    )
    assert {s.id for s in _run(api.list())} == {"s1", "s2"}
    # filtro por status preservado
    assert _run(api.list(status="running"))[0].id in {"s1", "s2"}
    with pytest.raises(PermissionError):
        _run(api.get("s3"))
    with pytest.raises(PermissionError):
        _run(api.focus("s3"))
    _run(api.focus("s1"))
    assert focused == ["s1"]


def test_sessions_focus_missing_raises():
    api = _PluginSessions(
        list_provider=lambda _status: [],
        focus_fn=lambda _id: None,
        inst=_FakePlugin(_perms("all")),
    )
    with pytest.raises(KeyError):
        _run(api.focus("nope"))


# -------------------- PluginHost factory defaults ---------------------------


def test_plugin_host_works_with_default_providers(tmp_path):
    """Sem providers, ctx.workspaces.list() retorna vazio (não crasha)."""
    # Isola registry pra não tocar em ~/.config
    import claude_workspaces.plugins.registry as reg_mod
    orig = reg_mod.plugins_dir
    reg_mod.plugins_dir = lambda: tmp_path / "registry"
    try:
        host = PluginHost()
        try:
            assert host.runtime is not None
            assert host.publish("workspace.opened", {"workspaceId": "x"}) == 0
        finally:
            host.shutdown()
    finally:
        reg_mod.plugins_dir = orig
