"""Testes do enforcement de ctx.fs e ctx.http (seção 8 da spec)."""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

from claude_workspaces.plugins.manifest import (  # noqa: E402
    FilesystemPermissions,
    NetworkPermissions,
    Permissions,
)
from claude_workspaces.services.plugin_host import _PluginFS, _PluginHttp  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _inst(perms):
    return SimpleNamespace(id="test", manifest=SimpleNamespace(permissions=perms))


# -------------------- ctx.fs --------------------


def _fs_perms(read=(), write=()):
    return Permissions(
        filesystem=FilesystemPermissions(read=tuple(read), write=tuple(write)),
        network=NetworkPermissions(),
        notifications=False,
        workspaces="all",
    )


def test_fs_read_allowed(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("oi", encoding="utf-8")
    fs = _PluginFS(_inst(_fs_perms(read=(str(tmp_path / "*.txt"),))))
    assert _run(fs.read(str(f))) == "oi"


def test_fs_read_blocked_outside_glob(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("oi", encoding="utf-8")
    other = tmp_path.parent / "outside.txt"
    fs = _PluginFS(_inst(_fs_perms(read=(str(tmp_path / "*.txt"),))))
    with pytest.raises(PermissionError):
        _run(fs.read(str(other)))


def test_fs_traversal_resolved_before_match(tmp_path):
    """`..` é resolvido antes do match — não escapa do glob declarado."""
    inside = tmp_path / "in.txt"
    inside.write_text("ok", encoding="utf-8")
    # Glob só permite tmp_path/*.txt. Path "tmp_path/sub/../in.txt" resolve
    # pra tmp_path/in.txt, que bate.
    (tmp_path / "sub").mkdir()
    sneaky = str(tmp_path / "sub" / ".." / "in.txt")
    fs = _PluginFS(_inst(_fs_perms(read=(str(tmp_path / "*.txt"),))))
    assert _run(fs.read(sneaky)) == "ok"

    # Mas se a glob fosse só tmp_path/sub/*.txt e o `..` te tirasse de lá,
    # bloqueia.
    fs2 = _PluginFS(_inst(_fs_perms(read=(str(tmp_path / "sub" / "*.txt"),))))
    with pytest.raises(PermissionError):
        _run(fs2.read(sneaky))


def test_fs_write_requires_write_permission(tmp_path):
    target = tmp_path / "out.txt"
    # só leitura → write deve falhar
    fs_ro = _PluginFS(_inst(_fs_perms(read=(str(tmp_path / "*.txt"),))))
    with pytest.raises(PermissionError):
        _run(fs_ro.write(str(target), "x"))

    # write declarado → ok
    fs_rw = _PluginFS(_inst(_fs_perms(write=(str(tmp_path / "*.txt"),))))
    _run(fs_rw.write(str(target), "x"))
    assert target.read_text() == "x"


def test_fs_list_requires_read(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.txt").write_text("", encoding="utf-8")
    fs = _PluginFS(_inst(_fs_perms(read=(str(tmp_path / "a"),))))
    assert _run(fs.list(str(tmp_path / "a"))) == ["x.txt"]
    fs_bad = _PluginFS(_inst(_fs_perms()))
    with pytest.raises(PermissionError):
        _run(fs_bad.list(str(tmp_path / "a")))


def test_fs_tilde_expansion(tmp_path, monkeypatch):
    """`~` deve expandir antes do match e do open."""
    monkeypatch.setenv("HOME", str(tmp_path))
    f = tmp_path / "h.txt"
    f.write_text("yo", encoding="utf-8")
    fs = _PluginFS(_inst(_fs_perms(read=("~/*.txt",))))
    assert _run(fs.read("~/h.txt")) == "yo"


# -------------------- ctx.http --------------------


def _http_perms(hosts=()):
    return Permissions(
        filesystem=FilesystemPermissions(),
        network=NetworkPermissions(hosts=tuple(hosts)),
        notifications=False,
        workspaces="all",
    )


def test_http_host_must_be_declared():
    http = _PluginHttp(_inst(_http_perms(hosts=("api.example.com",))))
    with pytest.raises(PermissionError):
        _run(http.get("https://evil.com/x"))


def test_http_rejects_non_http_scheme():
    http = _PluginHttp(_inst(_http_perms(hosts=("api.example.com",))))
    with pytest.raises(ValueError):
        _run(http.get("file:///etc/passwd"))


def test_http_no_partial_match():
    """`example.com` não inclui subdomínios — match é exato."""
    http = _PluginHttp(_inst(_http_perms(hosts=("example.com",))))
    with pytest.raises(PermissionError):
        _run(http.get("https://sub.example.com/x"))


def test_http_allows_declared_host(monkeypatch):
    """Sucesso real — mocking de urlopen pra não bater rede."""
    from claude_workspaces.plugin_api import HttpResponse

    captured = {}

    class _FakeResp:
        status = 200
        headers = {"Content-Type": "text/plain"}

        def read(self):
            return b"hello"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        return _FakeResp()

    monkeypatch.setattr(
        "urllib.request.urlopen", fake_urlopen
    )
    http = _PluginHttp(_inst(_http_perms(hosts=("api.example.com",))))
    resp = _run(http.get("https://api.example.com/v1"))
    assert isinstance(resp, HttpResponse)
    assert resp.status == 200
    assert resp.body == b"hello"
    assert captured["url"] == "https://api.example.com/v1"
    assert captured["method"] == "GET"
