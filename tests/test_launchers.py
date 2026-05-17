"""Testes do módulo launchers — foca em validação e construção de argv.

Os spawns reais são mockados; só checamos o que entra em subprocess.Popen
e como erros viram LauncherError com a mensagem certa.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_workspaces.launchers import (
    LauncherError,
    effective_shell,
    find_app_repo_root,
    launch_claude,
    launch_claude_in_dir,
    launch_claude_resume,
    launch_ide,
    launch_konsole,
)
from claude_workspaces.models import Workspace
from claude_workspaces.settings import Settings


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    folder = tmp_path / "proj"
    folder.mkdir()
    return Workspace(
        id="ws-test",
        name="Test",
        description="",
        folders=[str(folder)],
    )


@pytest.fixture
def settings() -> Settings:
    s = Settings()
    s.terminal_command = "konsole"
    s.claude_command = "claude"
    s.claude_extra_args = []
    return s


def test_effective_shell_prefers_settings():
    s = Settings()
    s.shell_command = "/usr/bin/fish"
    assert effective_shell(s) == "/usr/bin/fish"


def test_effective_shell_falls_back_to_passwd_or_env():
    s = Settings()
    s.shell_command = ""
    out = effective_shell(s)
    assert out.startswith("/") and "/" in out


def test_launch_claude_raises_without_folders(settings):
    empty = Workspace(id="x", name="x", description="", folders=[])
    with pytest.raises(LauncherError, match="não tem nenhuma pasta"):
        launch_claude(empty, settings)


def test_launch_claude_raises_when_terminal_missing(workspace, settings):
    with patch("claude_workspaces.launchers.shutil.which", return_value=None):
        with pytest.raises(LauncherError, match="não encontrado no PATH"):
            launch_claude(workspace, settings)


def test_launch_claude_argv_includes_extras(workspace, settings, tmp_path):
    extra = tmp_path / "extra-dir"
    extra.mkdir()
    workspace.folders.append(str(extra))
    settings.claude_extra_args = ["--debug"]

    with (
        patch("claude_workspaces.launchers.shutil.which", return_value="/usr/bin/konsole"),
        patch("claude_workspaces.launchers.subprocess.Popen") as popen,
    ):
        popen.return_value = MagicMock()
        launch_claude(workspace, settings)
    args, kwargs = popen.call_args
    argv = args[0]
    # Termina com "-ic" + shlex-joined comando
    assert argv[0] == "konsole"
    assert "-e" in argv
    assert "-ic" in argv
    inner = argv[-1]
    assert "claude" in inner
    assert "--debug" in inner
    assert "--add-dir" in inner


def test_launch_claude_resume_uses_session_id_and_cwd(workspace, settings, tmp_path):
    other_cwd = tmp_path / "other"
    other_cwd.mkdir()
    with (
        patch("claude_workspaces.launchers.shutil.which", return_value="/usr/bin/konsole"),
        patch("claude_workspaces.launchers.subprocess.Popen") as popen,
    ):
        popen.return_value = MagicMock()
        launch_claude_resume(workspace, settings, "session-123", cwd=str(other_cwd))
    argv = popen.call_args[0][0]
    inner = argv[-1]
    assert "--resume" in inner
    assert "session-123" in inner
    # cwd passado corretamente
    assert popen.call_args.kwargs.get("cwd") == str(other_cwd) or popen.call_args[1].get(
        "cwd"
    ) == str(other_cwd)


def test_launch_claude_in_dir_passes_cwd(tmp_path, settings):
    target = tmp_path / "dir"
    target.mkdir()
    with (
        patch("claude_workspaces.launchers.shutil.which", return_value="/usr/bin/konsole"),
        patch("claude_workspaces.launchers.subprocess.Popen") as popen,
    ):
        popen.return_value = MagicMock()
        launch_claude_in_dir(target, settings)
    assert popen.call_args.kwargs["cwd"] == str(target)


def test_launch_konsole_without_folders_errors(settings):
    ws = Workspace(id="x", name="x", description="", folders=[])
    with pytest.raises(LauncherError):
        launch_konsole(ws, settings)


def test_launch_ide_without_folders_errors(settings):
    ws = Workspace(id="x", name="x", description="", folders=[])
    with pytest.raises(LauncherError):
        launch_ide("intellij", ws, settings)


def test_launch_ide_unknown_command_errors(workspace, settings):
    # IDE não configurado → erro claro
    with pytest.raises(LauncherError, match="não definido"):
        launch_ide("nao-existe-ide", workspace, settings)


def test_find_app_repo_root_locates_pyproject():
    root = find_app_repo_root()
    # Pode achar (rodando do source) ou não (instalado via pip)
    if root is not None:
        assert (root / "pyproject.toml").exists()
        assert (root / "src" / "claude_workspaces").is_dir()
