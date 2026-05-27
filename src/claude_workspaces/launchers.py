import logging
import os
import pwd
import shlex
import shutil
import subprocess
from pathlib import Path

from .models import Workspace
from .settings import Settings

log = logging.getLogger(__name__)


def effective_shell(settings: Settings | None = None) -> str:
    """Resolve the shell to use for interactive command wrapping.

    Order: settings.shell_command (if set) → login shell from /etc/passwd →
    $SHELL env var → /bin/bash. The login shell is preferred over $SHELL
    because the harness may inject a different SHELL at runtime.
    """
    if settings and settings.shell_command:
        return settings.shell_command
    try:
        return pwd.getpwuid(os.getuid()).pw_shell
    except KeyError:
        return os.environ.get("SHELL", "/bin/bash")


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


def _spawn(argv: list[str], cwd: str | Path) -> subprocess.Popen:
    log.info("Spawning: %s (cwd=%s)", argv, cwd)
    try:
        return subprocess.Popen(argv, cwd=str(cwd))
    except OSError as e:
        log.exception("Falha ao iniciar processo: %s", argv)
        raise LauncherError(f"Falha ao iniciar processo: {e}") from e


def _run_in_terminal(
    settings: Settings,
    inner_cmd_parts: list[str],
    cwd: str | Path,
) -> subprocess.Popen:
    """Spawn the terminal, running the inner command through an interactive
    shell so user-defined aliases (e.g. `ia` → `claude`) resolve."""
    inner = shlex.join(inner_cmd_parts)
    return _spawn(
        [settings.terminal_command, "-e", effective_shell(settings), "-ic", inner],
        cwd,
    )


def launch_ai(workspace: Workspace, settings: Settings) -> None:
    """Launch the configured AI backend in external terminal."""
    if not workspace.folders:
        raise LauncherError(f"Workspace '{workspace.name}' não tem nenhuma pasta")
    _require(settings.terminal_command, "terminal")
    _require(settings.ai_command(), "ai")
    cwd, extras = workspace.launch_paths()
    if settings.ai_backend == "opencode":
        cmd = [settings.ai_command(), *settings.ai_launch_args(), cwd]
    else:
        cmd = [settings.ai_command(), *settings.ai_launch_args()]
        for extra in extras:
            cmd += ["--add-dir", extra]
    _run_in_terminal(settings, cmd, cwd)


def launch_ai_resume(
    workspace: Workspace, settings: Settings, session_id: str, cwd: str | None = None
) -> None:
    if not workspace.folders:
        raise LauncherError(f"Workspace '{workspace.name}' não tem nenhuma pasta")
    _require(settings.terminal_command, "terminal")
    _require(settings.ai_command(), "ai")
    ws_cwd, extras = workspace.launch_paths()
    effective_cwd = cwd or ws_cwd
    if settings.ai_backend == "opencode":
        cmd = [settings.ai_command(), *settings.ai_launch_args(), "-s", session_id, effective_cwd]
    else:
        cmd = [settings.ai_command(), *settings.ai_launch_args(), "--resume", session_id]
        for extra in extras:
            cmd += ["--add-dir", extra]
    _run_in_terminal(settings, cmd, effective_cwd)


def launch_ai_in_dir(directory: str | Path, settings: Settings) -> None:
    _require(settings.terminal_command, "terminal")
    _require(settings.ai_command(), "ai")
    cmd = [settings.ai_command(), *settings.ai_launch_args()]
    if settings.ai_backend == "opencode":
        cmd.append(str(directory))
    _run_in_terminal(settings, cmd, directory)


def launch_claude(workspace: Workspace, settings: Settings) -> None:
    return launch_ai(workspace, settings)


def launch_claude_resume(
    workspace: Workspace, settings: Settings, session_id: str, cwd: str | None = None
) -> None:
    return launch_ai_resume(workspace, settings, session_id, cwd)


def launch_claude_in_dir(directory: str | Path, settings: Settings) -> None:
    return launch_ai_in_dir(directory, settings)


def launch_konsole(workspace: Workspace, settings: Settings) -> None:
    if not workspace.folders:
        raise LauncherError(f"Workspace '{workspace.name}' não tem nenhuma pasta")
    _require(settings.terminal_command, "terminal")
    cwd, _ = workspace.launch_paths()
    _spawn([settings.terminal_command], cwd)


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
    cwd, _ = workspace.launch_paths()
    _spawn([cmd, *workspace.folders], cwd)


def open_file_in_editor(path: str | Path, settings: Settings) -> None:
    """Abre um arquivo individual no editor configurado (settings.
    file_open_command — default 'code'/VS Code). Aceita comando com args,
    ex.: 'code -r', 'subl -n', 'nvim'. Lança LauncherError se o executável
    não estiver no PATH."""
    cmd = (settings.file_open_command or "code").strip()
    if not cmd:
        raise LauncherError("Comando de abertura de arquivo não definido — ajuste em Configurações")
    parts = shlex.split(cmd)
    exe = parts[0]
    if not shutil.which(exe):
        raise LauncherError(
            f"'{exe}' não encontrado no PATH — ajuste o comando de abrir arquivo em Configurações"
        )
    p = Path(path)
    _spawn([*parts, str(p)], p.parent)


def launch_claude_for_runner_gen(
    workspace: Workspace, settings: Settings, prompt: str
) -> None:
    """Abre o CLI configurado no diretório do próprio claude-workspaces com
    um prompt inicial pra gerar um RunnerConfig."""
    _require(settings.terminal_command, "terminal")
    _require(settings.ai_command(), "ai")
    repo = find_app_repo_root()
    if repo is None:
        raise LauncherError(
            "Repositório do claude-workspaces não encontrado — gerador "
            "precisa rodar no diretório do projeto pra ler docs/runners-spec.md"
        )
    if settings.ai_backend == "opencode":
        cmd = [settings.ai_command(), *settings.ai_launch_args(), "--prompt", prompt, str(repo)]
    else:
        cmd = [settings.ai_command(), *settings.ai_launch_args(), prompt]
    _run_in_terminal(settings, cmd, repo)


def find_app_repo_root() -> Path | None:
    p = Path(__file__).resolve().parent
    for _ in range(8):
        if (p / "pyproject.toml").exists() and (p / "src" / "claude_workspaces").is_dir():
            return p
        if p == p.parent:
            break
        p = p.parent
    return None
