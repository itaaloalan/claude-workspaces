import pytest

from claude_workspaces.errors import LaunchError
from claude_workspaces.services import system_open


class _Recorder:
    def __init__(self, raise_fnf: bool = False):
        self.raise_fnf = raise_fnf
        self.calls: list[list[str]] = []

    def __call__(self, argv, *args, **kwargs):
        if self.raise_fnf:
            raise FileNotFoundError(argv[0])
        self.calls.append(list(argv))
        return object()


def test_open_in_file_manager_calls_xdg_open(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(system_open.subprocess, "Popen", rec)
    system_open.open_in_file_manager("/tmp/x")
    assert rec.calls == [["xdg-open", "/tmp/x"]]


def test_open_in_file_manager_xdg_missing(monkeypatch):
    monkeypatch.setattr(system_open.subprocess, "Popen", _Recorder(raise_fnf=True))
    with pytest.raises(LaunchError, match="xdg-open"):
        system_open.open_in_file_manager("/tmp/x")


def test_open_in_editor_uses_default_code(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(system_open.subprocess, "Popen", rec)
    system_open.open_in_editor("/tmp/x")
    assert rec.calls == [["code", "/tmp/x"]]


def test_open_in_editor_uses_custom_editor(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(system_open.subprocess, "Popen", rec)
    system_open.open_in_editor("/tmp/x", editor_command="nvim")
    assert rec.calls == [["nvim", "/tmp/x"]]


def test_open_in_editor_missing_raises(monkeypatch):
    monkeypatch.setattr(system_open.subprocess, "Popen", _Recorder(raise_fnf=True))
    with pytest.raises(LaunchError, match="nvim"):
        system_open.open_in_editor("/tmp/x", editor_command="nvim")


def test_open_url_calls_xdg_open(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(system_open.subprocess, "Popen", rec)
    system_open.open_url("https://example.com")
    assert rec.calls == [["xdg-open", "https://example.com"]]


def test_open_url_empty_is_noop(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(system_open.subprocess, "Popen", rec)
    system_open.open_url("")
    assert rec.calls == []


def test_open_url_xdg_missing_raises(monkeypatch):
    monkeypatch.setattr(system_open.subprocess, "Popen", _Recorder(raise_fnf=True))
    with pytest.raises(LaunchError, match="xdg-open"):
        system_open.open_url("https://example.com")
