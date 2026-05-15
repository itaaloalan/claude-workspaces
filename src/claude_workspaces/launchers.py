import os
import shlex
import shutil
import subprocess
from pathlib import Path

from .models import Workspace
from .settings import Settings


IDE_LABEL: dict[str, str] = {
    "intellij": "IntelliJ IDEA",
    "webstorm": "WebStorm",
    "pycharm": "PyCharm",
    "rider": "Rider",
    "vscode": "VS Code",
}


class LauncherError(Exception):
    pass


def _require(cmd: str, label: str | None = None) -> None:
    if not shutil.which(cmd):
        raise LauncherError(f"'{cmd}' não encontrado no PATH ({label or 'comando'})")


def _user_shell() -> str:
    return os.environ.get("SHELL", "/bin/bash")


def _run_in_terminal(
    terminal_cmd: str,
    inner_cmd_parts: list[str],
    cwd: str | Path,
) -> None:
    """Spawn the terminal, running the inner command through an interactive
    shell so user-defined aliases (e.g. `ia` → `claude`) resolve."""
    inner = shlex.join(inner_cmd_parts)
    subprocess.Popen(
        [terminal_cmd, "-e", _user_shell(), "-ic", inner],
        cwd=str(cwd),
    )


def launch_claude(workspace: Workspace, settings: Settings) -> None:
    if not workspace.primary_folder:
        raise LauncherError(f"Workspace '{workspace.name}' não tem nenhuma pasta")
    _require(settings.terminal_command, "terminal")
    cmd = [settings.claude_command, *settings.claude_extra_args]
    for extra in workspace.extra_folders:
        cmd += ["--add-dir", extra]
    _run_in_terminal(settings.terminal_command, cmd, workspace.primary_folder)


def launch_claude_in_dir(directory: str | Path, settings: Settings) -> None:
    _require(settings.terminal_command, "terminal")
    cmd = [settings.claude_command, *settings.claude_extra_args]
    _run_in_terminal(settings.terminal_command, cmd, directory)


def launch_konsole(workspace: Workspace, settings: Settings) -> None:
    if not workspace.primary_folder:
        raise LauncherError(f"Workspace '{workspace.name}' não tem nenhuma pasta")
    _require(settings.terminal_command, "terminal")
    subprocess.Popen([settings.terminal_command], cwd=workspace.primary_folder)


def launch_ide(ide_key: str, workspace: Workspace, settings: Settings) -> None:
    if not workspace.folders:
        raise LauncherError(f"Workspace '{workspace.name}' não tem nenhuma pasta")
    cmd = settings.ide_command(ide_key)
    if not cmd:
        raise LauncherError(f"Comando para {IDE_LABEL.get(ide_key, ide_key)} não definido")
    if not shutil.which(cmd):
        raise LauncherError(
            f"'{cmd}' não encontrado no PATH — ajuste o comando do {IDE_LABEL.get(ide_key, ide_key)} em Configurações"
        )
    subprocess.Popen([cmd, *workspace.folders])


def find_app_repo_root() -> Path | None:
    p = Path(__file__).resolve().parent
    for _ in range(8):
        if (p / "pyproject.toml").exists() and (p / "src" / "claude_workspaces").is_dir():
            return p
        if p == p.parent:
            break
        p = p.parent
    return None
