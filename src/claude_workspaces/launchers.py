import logging
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from .models import Workspace
from .settings import Settings


log = logging.getLogger(__name__)


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
        msg = f"'{cmd}' não encontrado no PATH ({label or 'comando'})"
        log.warning(msg)
        raise LauncherError(msg)


def _user_shell() -> str:
    return os.environ.get("SHELL", "/bin/bash")


def _spawn(argv: list[str], cwd: str | Path) -> subprocess.Popen:
    log.info("Spawning: %s (cwd=%s)", argv, cwd)
    try:
        return subprocess.Popen(argv, cwd=str(cwd))
    except OSError as e:
        log.exception("Falha ao iniciar processo: %s", argv)
        raise LauncherError(f"Falha ao iniciar processo: {e}") from e


def _run_in_terminal(
    terminal_cmd: str,
    inner_cmd_parts: list[str],
    cwd: str | Path,
) -> subprocess.Popen:
    """Spawn the terminal, running the inner command through an interactive
    shell so user-defined aliases (e.g. `ia` → `claude`) resolve."""
    inner = shlex.join(inner_cmd_parts)
    return _spawn(
        [terminal_cmd, "-e", _user_shell(), "-ic", inner],
        cwd,
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
    _spawn([settings.terminal_command], workspace.primary_folder)


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
    _spawn([cmd, *workspace.folders], workspace.primary_folder or Path.cwd())


def find_app_repo_root() -> Path | None:
    p = Path(__file__).resolve().parent
    for _ in range(8):
        if (p / "pyproject.toml").exists() and (p / "src" / "claude_workspaces").is_dir():
            return p
        if p == p.parent:
            break
        p = p.parent
    return None
